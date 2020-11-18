from __future__ import annotations
import inspect
from typing import Union, List, Optional, TypeVar, Type, Callable, Any
from src import CoreUtil as CU
import abc
import h5py
import logging
import numpy as np
import lmfit as lm
from dataclasses import dataclass
from src.HDF_Util import params_from_HDF, params_to_HDF, with_hdf_read, with_hdf_write
import src.HDF_Util as HDU
from functools import lru_cache, partial
from src.CoreUtil import MyLRU, my_partial
from deprecation import deprecated
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.DatObject.DatHDF import DatHDF

logger = logging.getLogger(__name__)

FIT_NUM_BINS = 1000  # TODO: This should be somewhere else (use in FitInfo)


class DatAttribute(abc.ABC):
    @property
    @abc.abstractmethod
    def version(self):
        """Should returns something like '1.0.0 (major.feature_breaking.feature[.bug])'

        Note does not need to be a whole property to override.. can just be "version = '1.0'"
        at the top of the class"""
        # FIXME: This needs to be a bit more clever... Should read version from HDF if exists, otherwise should set in HDF based on class version
        return

    @property
    @abc.abstractmethod
    def group_name(self):
        """Should return name of group in HDF (i.e. 'Transition')

        Note: does not need to be a whole property override, can just be a class variable"""
        return

    @property
    @abc.abstractmethod
    def description(self):
        """Should be a short description of what this DatAttribute does (for human reading only)

        Note: Does not need to be a whole property, can just be a class variable
        """
        return

    def __init__(self, dat: DatHDF):
        self.dat = dat  # Save pointer to parent DatHDF object
        self.hdf = dat.hdf
        self.check_init()  # Ensures in minimally initialized state

    @property
    def time_initialized(self):
        return self._get_time_initialized()

    @property
    def initialized(self):
        return self._get_initialized_state()

    @initialized.setter
    def initialized(self, value):
        assert isinstance(value, bool)
        self.set_group_attr('initialized', value)

    def set_group_attr(self, name: str, value, group_name: str = None):
        """
        Can be used to store attributes in HDF group, optionally in a named group
        Args:
            name (str): Name of attribute to store in HDF
            value (any): Any HDU.allowed() value to store in HDF
            group_name (str): Optional full path to the group in which the value should be stored

        Returns:
            None
        """
        if HDU.allowed(value):
            group_name = group_name if group_name else self.group_name
            self._set_attr(group_name, name, value)
        else:
            raise TypeError(f'{value} not allowed in HDF')

    @with_hdf_read
    def get_group_attr(self, name: str, default=None, check_exists: bool = False, group_name: Optional[str] = None,
                       dataclass: Type[DatDataclassTemplate] = None):
        """
        Used to get a value from the HDF group, optionally from named group
        Args:
            name (str): Name of attribute in HDF
            default (any): Value to default to if not found
            check_exists (bool): Whether to raise an error if not found
            group_name (Optional[str]): Optional full path to the group in which the value is stored (the parent group
                to the value, even if the value is stored as a group itself)
            dataclass (): Optional DatDataclass which can be used to load the information back into dataclass form

        Returns:
            any
        """
        group_name = group_name if group_name else self.group_name
        group = self.hdf.get(group_name)
        return HDU.get_attr(group, name, default=default, check_exists=check_exists, dataclass=dataclass)

    @with_hdf_write
    def _set_attr(self, group_name, name, value):
        group = self.hdf.get(group_name)
        HDU.set_attr(group, name, value)

    @with_hdf_read
    def check_init(self):
        group = self.hdf.get(self.group_name, None)
        if group is None:
            self._create_group(self.group_name)
            group = self.hdf.get(self.group_name)
        if group.attrs.get('initialized', False) is False:
            self._initialize()

    @with_hdf_write
    def _initialize(self):
        self._initialize_minimum()
        self._write_default_group_attrs()
        assert self.initialized == True
        self.set_group_attr('date_initialized', str(CU.time_now()))

    @with_hdf_read
    def _get_initialized_state(self):
        group = self.hdf.get(self.group_name)
        return HDU.get_attr(group, 'initialized', False)

    @abc.abstractmethod
    @with_hdf_write
    def _initialize_minimum(self):
        """Override this to do whatever needs to be done to MINIMALLY initialize the HDF
        i.e. this should be as fast as possible, leaving any intensive stuff to be done lazily or in a separate
        call
        Should not be called directly as it will be called as part of DatAttribute init
        (which also does other group attrs)

        Note: Don't forget to set self.initialized = True
        """
        # Do stuff
        self.initialized = True  # Then set this True
        pass

    @with_hdf_write
    def initialize_maximum(self):
        """Use this to run all initialization (i.e. all intensive time consuming stuff). Ideally this will be run
        in the background at some point"""
        logger.warning(f'No "initialize_max" implemented for {self.__class__}')
        pass

    @with_hdf_read
    def _get_time_initialized(self):
        group = self.hdf.get(self.group_name)
        time = group.attrs.get('time_initialized', None)
        return time

    @with_hdf_write
    def _create_group(self, group_name):
        if group_name not in self.hdf.keys():
            self.hdf.create_group(group_name)

    @with_hdf_read
    def _check_default_group_attrs(self):
        """Set default attributes of group if not already existing
        e.g. upon creation of new dat, add description of group in attrs"""
        group = self.hdf.get(self.group_name)
        if {'version', 'description'} - set(group.attrs.keys()):
            self._write_default_group_attrs()

    @with_hdf_write
    def _write_default_group_attrs(self):
        """Writes the default group attrs"""
        group = self.hdf.get(self.group_name)
        version = self.version
        description = self.description
        group.attrs['version'] = version
        group.attrs['description'] = description

    def property_prop(self, attr_name: str, group_name: Optional[str] = None,
                      dataclass: Type[DatDataclassTemplate] = None) -> Any:
        """
        Use this to help make shorthand properties for getting attrs from HDF group
        Args:
            attr_name (): Name of attribute to look for
            group_name (): Optional full group path to look for attribute in
            dataclass (): If loading something that was saved as a dataclass, must load with the same dataclass

        Returns:
            Whatever was stored in the HDF under the attr_name
        """
        private_key = self._get_private_key(attr_name)
        if not getattr(self, private_key, None):
            setattr(self, private_key, self.get_group_attr(attr_name, check_exists=True, group_name=group_name, dataclass=dataclass))
        return getattr(self, private_key)

    def property_set(self, attr_name: str, value: Any, group_name: Optional[str] = None):
        """Use this to help make shorthand properties for setting attrs in HDF group
        Note: Don't use this if you want the attribute to be read only
        """
        private_key = self._get_private_key(attr_name)
        if HDU.allowed(value):
            self.set_group_attr(attr_name, value, group_name=group_name)
            setattr(self, private_key, value)
        else:
            raise TypeError(f'{value} with type {type(value)} not allowed in HDF according to HDU.allowed()')

    def property_del(self, attr_name: str, group_name: Optional[str] = None):
        """Use this to help make shorthand properties for deleting attrs in HDF group
        Note: Don't use this if you dont want the attribute to be deletable"""
        private_key = self._get_private_key(attr_name)
        if getattr(self, private_key, None):
            delattr(self, private_key)
        raise NotImplementedError(f"Haven't implemented removing attributes from HDF yet")  # TODO: implement this

    @staticmethod
    def _get_private_key(attr_name):
        return '_'+attr_name

    # @abc.abstractmethod
    # @with_hdf_read
    # def get_from_HDF(self):
    #     """Should be able to run this to get all data from HDF into expected attrs of DatAttr (remember to use
    #     context manager to open HDF)"""
    #     pass

    # @abc.abstractmethod
    # @with_hdf_write
    # def update_HDF(self):
    #     """Should be able to run this to set all data in HDF s.t. loading would return to current state"""
    #     group = self.hdf.get(self.group_name)
    #     group.attrs['version'] = self.__class__.version

    def clear_caches(self):
        """Should clear out any caches (or equivalent of caches)
        e.g. self.cached_method.clear_cache() if using @functools.LRU_cache, or del self._<manual_cache>"""
        logger.warning(f'Clear cache has not been overwritten for {self.__class__} so has no effect')
        pass


T = TypeVar('T', bound='DatDataclassTemplate')  # Required in order to make subclasses return their own subclass


@dataclass
class DatDataclassTemplate(abc.ABC):
    """
    This provides some useful methods, and requires the necessary overrides s.t. a dataclass with most types of info
    can be saved in a HDF file and be loaded from an HDF file

    Any Dataclasses which are going to be stored in HDF should inherit from this. This provides a method to save to
    hdf as well as a class method to load back from the hdf.

    NOTE: Also make sure parent_group is CLOSED after calling save_to_hdf or from_hdf !!!

    e.g.
        @dataclass
        class Test(DatDataClassTemplate):
            a: int
            b: str = field(default = "Won't show in repr", repr = False)

        d = Test(1)
        d.save_to_hdf(group)  # Save in group with default dataclass name (Test)
        e = Test.from_hdf(group)  # Load from group (will have the same settings as initial dataclass)
    """

    def save_to_hdf(self, parent_group: h5py.Group, name: Optional[str] = None):
        """
        Default way to save all info from Dataclass to HDF in a way in which it can be loaded back again. Override this
        to save more complex dataclasses.
        Make sure if you override this that you override "from_hdf" in order to get the data back again.

        Args:
            parent_group (h5py.Group): The group in which the dataclass should be saved (i.e. it will create it's own group in
                here)
            name (Optional[str]): Optional specific name to store dataclass with, otherwise defaults to Dataclass name

        Returns:
            None
        """
        if name is None:
            name = self._default_name()
        dc_group = parent_group.require_group(name)
        self._save_standard_attrs(dc_group, ignore_keys=self.ignore_keys_for_saving())

    def ignore_keys_for_saving(self) -> Optional[Union[str, List[str]]]:
        """Override this to ignore specific dataclass keys when saving to HDF"""
        return None

    @classmethod
    def from_hdf(cls: Type[T], parent_group: h5py.Group, name: Optional[str] = None) -> T:
        """
        Should get back all data saved to HDF with "save_to_hdf" and initialize the dataclass and return that instance
        Remember to override this when overriding "save_to_hdf"

        Args:
            parent_group (h5py.Group): The group in which the saved data should be found (i.e. it will be a sub group in this
                group)
            name (Optional[str]): Optional specific name to look for if saved with a specific name, otherwise defaults
                to the name of the Dataclass

        Returns:
            (T): Returns and instance of cls. Should have the correct typing. Or will return None with a warning if
            no data is found.
        """
        if name is None:
            name = cls._default_name()
        dc_group = parent_group.get(name)

        if dc_group is None:
            raise FileNotFoundError(f'No {name} group in {parent_group.name}')

        d = cls._get_standard_attrs_dict(dc_group)
        inst = cls(**d)
        return inst

    def _save_standard_attrs(self, group: h5py.Group, ignore_keys: Optional[Union[str, List[str]]] = None):
        ignore_keys = CU.ensure_set(ignore_keys)
        for k in set(self.__annotations__) - ignore_keys:
            val = getattr(self, k)
            if isinstance(val, (np.ndarray, h5py.Dataset)) and val.size > 1000:
                HDU.set_data(group, k, val)
            elif HDU.allowed(val):
                HDU.set_attr(group, k, val)
            else:
                logger.warning(
                    f'{self.__class__.__name__}.{k} = {val} which has type {type(val)} (where type {self.__annotations__[k]} was expected) which is not able to be saved automatically. Override "save_to_hdf" and "from_hdf" in order to save and load this variable')

    @classmethod
    def _get_standard_attrs_dict(cls, group: h5py.Group, keys=None):
        assert isinstance(group, h5py.Group)
        d = dict()
        if keys is None:
            keys = cls.__annotations__
        for k in keys:
            d[k] = HDU.get_attr(group, k, None)
        return d

    @classmethod
    def _default_name(cls):
        return cls.__name__


class Values(object):
    """Object to store Init/Best values in and stores Keys of those values in self.keys"""

    def __init__(self):
        self.keys = []

    def __getattr__(self, item):
        if item.startswith('__') or item.startswith(
                '_') or item == 'keys':  # So don't complain about things like __len__
            return super().__getattribute__(item)  # Come's here looking for Ipython variables
        else:
            if item in self.keys:
                return super().__getattribute__(item)
            else:
                msg = f'{item} does not exist. Valid keys are {self.keys}'
                print(msg)
                logger.warning(msg)
                return None

    def get(self, item, default=None):
        if item in self.keys:
            val = self.__getattr__(item)
        else:
            val = default
        return val

    def __setattr__(self, key, value):
        if key.startswith('__') or key.startswith('_') or key == 'keys' or not isinstance(value, (
                np.number, float, int, type(None))):  # So don't complain about
            # things like __len__ and don't keep key of random things attached to class
            super().__setattr__(key, value)
        else:  # probably is something I want the key of
            self.keys.append(key)
            super().__setattr__(key, value)

    def __repr__(self):
        string = ''
        for key in self.keys:
            string += f'{key}={self.__getattr__(key):.5g}\n'
        return string


@dataclass
class FitInfo(DatDataclassTemplate):
    params: Union[lm.Parameters, None] = None
    func_name: Union[str, None] = None
    func_code: Union[str, None] = None
    fit_report: Union[str, None] = None
    model: Union[lm.Model, None] = None
    best_values: Union[Values, None] = None
    init_values: Union[Values, None] = None

    # Will only exist when set from fit, or after recalculate_fit
    fit_result: Union[lm.model.ModelResult, None] = None

    def init_from_fit(self, fit: lm.model.ModelResult):
        """Init values from fit result"""
        if fit is None:
            logger.warning(f'Got None for fit to initialize from. Not doing anything.')
            return None
        assert isinstance(fit, lm.model.ModelResult)
        self.params = fit.params
        self.func_name = fit.model.func.__name__

        #  Can't get source code when running from deepcopy (and maybe other things will break this)
        try:
            func_code = inspect.getsource(fit.model.func)
        except OSError:
            if self.func_code is not None:
                func_code = '[WARNING: might not be correct as fit was re run and could not get source code' + self.func_code
            else:
                logger.warning('Failed to get source func_code and no existing func_code')
                func_code = 'Failed to get source code due to OSError'
        self.func_code = func_code

        self.fit_report = fit.fit_report()
        self.model = fit.model
        self.best_values = Values()
        self.init_values = Values()
        for key in self.params.keys():
            par = self.params[key]
            self.best_values.__setattr__(par.name, par.value)
            self.init_values.__setattr__(par.name, par.init_value)

        self.fit_result = fit

    def init_from_hdf(self, group: h5py.Group):
        """Init values from HDF file"""
        self.params = params_from_HDF(group)
        self.func_name = group.attrs.get('func_name', None)
        self.func_code = group.attrs.get('func_code', None)
        self.fit_report = group.attrs.get('fit_report', None)
        self.model = lm.models.Model(self._get_func())
        self.best_values = Values()
        self.init_values = Values()
        for key in self.params.keys():
            par = self.params[key]
            self.best_values.__setattr__(par.name, par.value)
            self.init_values.__setattr__(par.name, par.init_value)

        self.fit_result = None

    def save_to_hdf(self, parent_group: h5py.Group, name: Optional[str] = None):
        if name is None:
            name = self._default_name()
        parent_group = parent_group.require_group(name)

        if self.params is None:
            logger.warning(f'No params to save for {self.func_name} fit. Not doing anything')
            return None
        params_to_HDF(self.params, parent_group)
        parent_group.attrs['description'] = 'FitInfo'  # Overwrites what params_to_HDF sets
        parent_group.attrs['func_name'] = self.func_name
        parent_group.attrs['func_code'] = self.func_code
        parent_group.attrs['fit_report'] = self.fit_report
        parent_group.file.flush()

    def _get_func(self):
        """Cheeky way to get the function which was used for fitting (stored as text in HDF so can be executed here)
        Definitely not ideal, so I at least check that I'm not overwriting something, but still should be careful here"""
        return HDU.get_func(self.func_name, self.func_code)

    def eval_fit(self, x: np.ndarray):
        """Return best fit for x array using params"""
        return self.model.eval(self.params, x=x)

    def eval_init(self, x: np.ndarray):
        """Return init fit for x array using params"""
        init_pars = CU.edit_params(self.params, list(self.params.keys()),
                                   [par.init_value for par in self.params.values()])
        return self.model.eval(init_pars, x=x)

    def recalculate_fit(self, x: np.ndarray, data: np.ndarray, auto_bin=False):
        """Fit to data with x array and update self"""
        assert data.ndim == 1
        data, x = CU.remove_nans(data, x)
        if auto_bin is True and len(data) > FIT_NUM_BINS:
            logger.info(f'Binning data of len {len(data)} into {FIT_NUM_BINS} before fitting')
            x, data = CU.bin_data([x, data], round(len(data) / FIT_NUM_BINS))
        fit = self.model.fit(data.astype(np.float32), self.params, x=x, nan_policy='omit')
        self.init_from_fit(fit)

    def edit_params(self, param_names=None, values=None, varys=None, mins=None, maxs=None):
        self.params = CU.edit_params(self.params, param_names, values, varys, mins, maxs)

    @classmethod
    def from_fit(cls, fit):
        inst = cls()
        inst.init_from_fit(fit)
        return inst

    @classmethod
    def from_hdf(cls, parent_group: h5py.Group, name: str = None):
        if name is None:
            name = cls._default_name()
        fg = parent_group.get(name)
        inst = cls()
        inst.init_from_hdf(fg)
        return inst


class FittingAttribute(DatAttribute, abc.ABC):

    @MyLRU
    @with_hdf_read
    def get_data(self, key):
        group = self.hdf.get(self.group_name).get('Data')
        data = HDU.get_data(group, key)
        return data

    @with_hdf_write
    def set_data(self, key: str, value: np.ndarray):
        group: h5py.Group = self.hdf.get(self.group_name).get('Data')
        HDU.set_data(group, key, value)
        self.get_data.cache_replace(value, key)  # Replace value in cache directly (adds if not already there)

    def __init__(self, hdf):
        super().__init__(hdf)
        self._avg_fit = None
        self._all_fits = None

    x: np.ndarray = property(my_partial(get_data, 'x', arg_start=1),
                             my_partial(set_data, 'x', arg_start=1))
    y: np.ndarray = property(my_partial(get_data, 'y', arg_start=1),
                             my_partial(set_data, 'y', arg_start=1))
    data: np.ndarray = property(my_partial(get_data, 'data', arg_start=1),
                                my_partial(set_data, 'data', arg_start=1))
    avg_data: np.ndarray = property(my_partial(get_data, 'avg_data', arg_start=1),
                                    my_partial(set_data, 'avg_data', arg_start=1))
    avg_data_err: np.ndarray = property(my_partial(get_data, 'avg_data_err', arg_start=1),
                                        my_partial(set_data, 'avg_data_err', arg_start=1))

    AUTO_BIN_SIZE = 1000  # TODO: Think about how to handle this better

    @property
    def avg_fit(self):
        """Easy to access property to get last used avg_fit"""
        if not self._avg_fit:
            self._avg_fit = self.get_avg_fit(params=None)  # Get default or last set fit
        return self._avg_fit

    @avg_fit.setter
    def avg_fit(self, fit: Union[lm.model.ModelResult, FitInfo]):
        fit = ensure_fit(fit)
        self._avg_fit = fit  # So self.avg_fit will return last set fit
        group_name = '/'.join((self.group_name, 'Avg fit'))
        self._save_fit(fit, group_name)

    @property
    def all_fits(self):
        """Easy to access property to get last used all_fits"""
        if not self._all_fits:
            self._all_fits = [self.get_row_fit(params=None, row=i) for i in range(len(self.y))]
        return self._all_fits

    def get_avg_fit(self, params: lm.Parameters=None, func: Optional[Callable[[Any], float]]=None) -> FitInfo:
        fit = self._get_fit(params=params, func=func, mode='avg')
        return fit

    def get_row_fit(self, params: Optional[lm.Parameters] = None, func: Optional[Callable[[Any], float]] = None, row: int = 0) -> FitInfo:
        fit = self._get_fit(params=params, func=func, mode='row', row=row)
        return fit

    @lru_cache
    def _get_fit(self, params: lm.Parameters=None, func: Optional[Callable[[Any], float]]=None, mode:str = 'avg', row: int=0) -> FitInfo:
        """Called by get_avg_fit and get_row_fit to try load from HDF, and then try Calculating otherwise"""
        if params is None:
            params = self.get_default_params()  # TODO: FIXME: Need to decide whether to get param estimates here or not
        if func is None:
            func = self.get_default_func()
        if mode == 'avg':
            group_name = '/'.join((self.group_name, 'Avg fit'))
        elif mode == 'row':
            group_name = '/'.join((self.group_name, 'Row fits', row))
        else:
            raise ValueError(f'mode must be "avg" or "row"')
        fit = self._load_fit(params, func, group_name)  # Try load from HDF first
        if fit is None:
            if mode == 'avg':
                data = self.avg_data
            elif mode == 'row':
                data = np.atleast_2d(self.data)[row]
            else:
                raise ValueError(f'mode must be "avg" or "row"')
            fit = self._calculate_fit(data=data, params=params, func=func)
            self._save_fit(fit, group_name)
        return fit

    @with_hdf_read
    def _load_fit(self, params, func, group_name) -> Union[FitInfo, None]:
        """Try find fit in group given"""
        name = self._get_fit_name(params, func)
        group = self.hdf.get(group_name)
        if name in group.keys():
            fit = FitInfo.from_hdf(group, name)
        else:
            fit = None
        return fit

    @with_hdf_write
    def _save_fit(self, fit: FitInfo, group_name):
        """Should store avg_fit's in avg_fit group where each fit is stored based on params/func"""
        fit_name = self._get_fit_name(fit.params, fit.model.func)  # Generate a fit name from params/func etc
        group = self.hdf.get(group_name)
        fit.save_to_hdf(group, fit_name)

    def _get_fit_name(self, params: lm.Parameters, func: Callable[[Any], float]):
        # TODO: make name based on params/func (also number so it's easy to tell which is first/last)
        name = f'{func.__name__}.{str(params)}'
        return name

    def _calculate_fit(self, data: np.ndarray, params: lm.Parameters, func: Callable[[Any], float], auto_bin=True) -> FitInfo:
        model = lm.model.Model(func)
        if auto_bin and data.shape[-1] > self.AUTO_BIN_SIZE:
            data = CU.bin_data(data, self.AUTO_BIN_SIZE)
        fit = FitInfo.from_fit(model.fit(data, params, nan_policy='omit'))
        return fit

    @abc.abstractmethod
    def get_default_params(self, data=None) -> lm.Parameters:
        """Should return lm.Parameters with default values, or estimates based on data passed in"""
        pass

    @abc.abstractmethod
    def get_default_func(self) -> Callable[[Any], float]:
        """Should return function to use for fitting model"""
        pass

    @with_hdf_write
    def _initialize_minimum(self):
        # todo: copy links of relevant data from Data to self.Group.Data
        # TODO: create required group folders
        group = self.hdf.get(self.group_name)
        dg = group.require_group('Data')
        group.require_group('Avg fit')
        group.require_group('Row fits')
        self.get_data_from_Data()

    @abc.abstractmethod
    def get_data_from_Data(self):
        """Override this to get the necessary data from dat.Data class
        Note: try to link if possible so data isn't duplicated

        Use 'data' as the name for the main data which will be fit to take advantage of methods in this class
        """
        # from = key in dat.Data, to = key in DatAttr.Data
        from_to = {'x_array': 'x',
                   'y_array': 'y',
                   'i_sense': 'data'}
        self._copy_data(from_to)

    @with_hdf_write
    def _copy_data(self, from_to_dict: dict):
        """Looks for data in dat.Data class, if it exists it makes a link to it in self.group.Data"""
        dat_data = self.dat.Data
        existing_data = dat_data.data_keys
        orig_data_group, attr_data_group = [self.hdf.get(name) for name in [self.dat.Data.group_name,
                                                                            self.group_name+'/Data']]
        missing_data = []
        for k in from_to_dict:
            if k in existing_data and k not in attr_data_group.keys():
                HDU.link_data(orig_data_group, attr_data_group, k, from_to_dict[k])
            else:
                missing_data.append(k)
        if missing_data:
            raise FileNotFoundError(f'{missing_data} not found in dat.Data and does not already exist in DatAttr.Data. '
                                    f'All other data was linked. Should be able to manually set this data and carry on')

    def clear_caches(self):
        self.get_data.clear_cache()
        self._get_fit.clear_cache()

    # @abc.abstractmethod
    # def set_avg_data(self, centers, x_array=None):
    #     """Make average data by centering rows of self.data with centers (defined on original x_array or x_array)
    #      then averaging then save to HDF
    #
    #     Args:
    #         centers (Union[np.ndarray, str]): Center positions defined on x_array or original x_array by default
    #         x_array (np.ndarray): Optional x_array which centers were defined on
    #
    #     Returns:
    #         None: Sets self.avg_data, self.avg_data_err and saves to HDF
    #     """
    #     x = x_array if x_array is not None else self.x
    #     if self.data.ndim == 1:
    #         self.avg_data = self.data
    #         self.avg_data_err = np.nan
    #     else:
    #         if centers is None:
    #             logger.warning(f'Averaging data with no centers passed')
    #             centered_data = self.data
    #         elif centers == 'None':  # Explicit no centering, so no need for warning
    #             centered_data = self.data
    #         else:
    #             centered_data = CU.center_data(x, self.data, centers)
    #         if np.sum(~np.isnan(centered_data)) < 20:
    #             logger.warning(f'Failed to center data for transition fit. Blind averaging instead')
    #             centered_data = self.data
    #         self.avg_data = np.nanmean(centered_data, axis=0)
    #         self.avg_data_err = np.nanstd(centered_data, axis=0)
    #     self._set_avg_data_hdf()

    # @abc.abstractmethod
    # def _set_avg_data_hdf(self):
    #     """Save average data to HDF"""
    #     dg = self.group['Data']
    #     self.hdf.flush()
    #     # dg['avg_i_sense'] = self.avg_data
    #     # dg['avg_i_sense_err'] = self.avg_data_err

    # @abc.abstractmethod
    # def run_avg_fit(self, fitter=None, params=None, auto_bin=True):
    #     """Run fit on average data"""
    #     if self.avg_data is None:
    #         logger.info('self.avg_data was none, running set_avg_data first')
    #         self.set_avg_data(centers=None)
    #     assert all([data is not None for data in [self.x, self.avg_data]])
    #
    #     if params is None:
    #         if hasattr(self.avg_fit, 'params'):
    #             params = self.avg_fit.params
    #         else:
    #             params = None
    #
    #     if fitter is None:
    #         return params  # Can use up to here by calling super().run_row_fits(params=params)
    #
    #     elif fitter is not None:  # Otherwise implement something like this in override
    #         x = self.x[:]
    #         data = self.avg_data[:]
    #         fit = fitter(x, data, params, auto_bin=auto_bin)[0]  # Note: Expecting to returned a list of 1 fit.
    #         fit_info = FitInfo()
    #         fit_info.init_from_fit(fit)
    #         self.avg_fit = fit_info
    #         self._set_avg_fit_hdf()
    #     else:
    #         raise NotImplementedError


def ensure_fit(fit: Union[FitInfo, lm.model.ModelResult]):
    if isinstance(fit, FitInfo):
        pass
    elif isinstance(fit, lm.model.ModelResult):
        fit = FitInfo.from_fit(fit)
    else:
        raise ValueError(f'trying to set avg_fit to something which is not a fit')
    return fit


def row_fits_to_group(group, fits, y_array=None):
    """For saving all row fits in a dat in a group. To get back to original, use rows_group_to_all_FitInfos"""
    if y_array is None:
        y_array = [None] * len(fits)
    else:
        assert len(y_array) == len(fits)
    for i, (fit_info, y_val) in enumerate(zip(fits, y_array)):
        name = f'Row{i}:{y_val:.5g}' if y_val is not None else f'Row{i}'
        row_group = group.require_group(name)
        row_group.attrs['row'] = i  # Used when rebuilding to make sure things are in order
        row_group.attrs['y_val'] = y_val if y_val is not None else np.nan
        fit_info.save_to_hdf(row_group)


@deprecated(details="Use what is in FittingAttributue class")
def rows_group_to_all_FitInfos(group: h5py.Group):
    """For loading row fits saved with row_fits_to_group"""
    row_group_dict = {}
    for key in group.keys():
        row_id = group[key].attrs.get('row', None)
        if row_id is not None:
            if group[key].attrs.get('description',
                                    None) == "FitInfo":  # Old as of 18/9/2020 (But here for backwards compatability)
                row_group_dict[row_id] = group[key]
            elif 'FitInfo' in group[key].keys():  # New way data is stored as of 18/9/2020
                row_group_dict[row_id] = group[key].get('FitInfo')
            else:
                raise NotImplementedError(f'Something has gone wrong... fit seems to exist in HDF, but cant find group')
    fit_infos = [FitInfo() for _ in row_group_dict]  # Makes a new FitInfo() [FI()]*10 just gives 10 pointers to 1 obj
    for key in sorted(
            row_group_dict.keys()):  # TODO: Old way of loading FitInfo, but need to not break backwards compatability if possible. This works but is not ideal
        fit_infos[key].init_from_hdf(row_group_dict[key])
    return fit_infos


def fit_group_to_FitInfo(group: h5py.Group):
    """For loading a single Fit group from HDF (i.e. if saved using FitInfo.save_to_hdf()"""
    assert group.attrs.get('description', None) in ["FitInfo", 'Single Parameters of fit']
    fit_info = FitInfo()
    fit_info.init_from_hdf(group)
    return fit_info


if __name__ == '__main__':
    from src.CoreUtil import my_partial

    class Test:

        def prop(self, key):
            # print(self.d, key)
            return key

        def setter(self, key, value):
            print(f'key={key}, value={value}')

        a = property(my_partial(prop, 'a', arg_start=1), my_partial(setter, 'a', arg_start=1))
        b = property(my_partial(prop, 'b', arg_start=1), my_partial(setter, 'b', arg_start=1))
        d = 10
        c = partial(prop, 'c')
        e = my_partial(setter, 'a', arg_start=1)


    t = Test()