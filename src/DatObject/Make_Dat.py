"""This is where ExpSpecific is used to get data into a standard form to be passed to DatBuilders which
make DatHDFs"""
from __future__ import annotations
import os
import logging

from src.DatObject.DatHDF import DatHDF, get_dat_id, DatHDFBuilder
from singleton_decorator import singleton
import src.HDF_Util as HDU
from typing import TYPE_CHECKING, Union, Iterable, Tuple, List
import threading
if TYPE_CHECKING:
    from src.DataStandardize.BaseClasses import Exp2HDF

from src.DataStandardize.ExpSpecific.Sep20 import SepExp2HDF
from src.DataStandardize.ExpSpecific.Feb21 import Feb21Exp2HDF
from src.DataStandardize.ExpSpecific.FebMar21 import FebMar21Exp2HDF

# default_Exp2HDF = SepExp2HDF
# default_Exp2HDF = Feb21Exp2HDF
default_Exp2HDF = FebMar21Exp2HDF

logger = logging.getLogger(__name__)


sync_lock = threading.Lock()


@singleton  # Necessary when only calling on class variables anyway?
class DatHandler(object):
    """
    Holds onto references to open dats (so that I don't try open the same datHDF more than once). Will return
    same dat instance if already open.
    Can also see what dats are open, remove individual dats from DatHandler, or clear all dats from DatHandler
    """
    open_dats = {}

    @classmethod
    def get_dat(cls, datnum: int, datname='base', overwrite=False,  init_level='min', exp2hdf: type(Exp2HDF) = None) \
            -> DatHDF:
        exp2hdf = exp2hdf(datnum=datnum, datname=datname) if exp2hdf else \
            default_Exp2HDF(datnum=datnum, datname=datname)
        full_id = f'{exp2hdf.ExpConfig.dir_name}:{get_dat_id(datnum, datname)}'  # For temp local storage
        path = exp2hdf.get_datHDF_path()
        cls._ensure_dir(path)
        if overwrite:
            cls._delete_hdf(path)
            if full_id in cls.open_dats:
                del cls.open_dats[full_id]

        if full_id not in cls.open_dats:  # Need to open or create DatHDF
            if os.path.isfile(path):
                cls.open_dats[full_id] = cls._open_hdf(path)
            else:
                cls._check_exp_data_exists(exp2hdf)
                builder = DatHDFBuilder(exp2hdf, init_level)
                cls.open_dats[full_id] = builder.build_dat()
        return cls.open_dats[full_id]

    @classmethod
    def get_dats(cls, datnums: Union[Iterable[int], Tuple[int, int]], datname='base', overwrite=False, init_level='min',
                 exp2hdf=None) -> List[DatHDF]:
        """Convenience for loading multiple dats at once, just calls get_dat multiple times"""
        # TODO: Make this multiprocess/threaded especially if overwriting or if dat does not already exist!
        if type(datnums) == tuple and len(datnums) == 2:
            datnums = range(*datnums)
        return [cls.get_dat(num, datname=datname, overwrite=overwrite, init_level=init_level, exp2hdf=exp2hdf)
                for num in datnums]

    @staticmethod
    def _ensure_dir(path):
        dir_path = os.path.dirname(path)
        if not os.path.isdir(dir_path):
            logger.warning(f'{dir_path} was not found, being created now')
            os.makedirs(dir_path, exist_ok=True)

    @staticmethod
    def _delete_hdf(path: str):
        """Should delete hdf if it exists"""
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _open_hdf(path: str):
        hdf_container = HDU.HDFContainer.from_path(path)
        dat = DatHDF(hdf_container)
        return dat

    @staticmethod
    def _check_exp_data_exists(exp2hdf: Exp2HDF):
        exp_path = exp2hdf.get_exp_dat_path()
        if os.path.isfile(exp_path):
            return True
        else:
            with sync_lock:
                if not os.path.isfile(exp_path):  # Might be there by time lock is released
                    exp2hdf.synchronize_data()  # Tries to synchronize data from server then check for path again.
                if os.path.isfile(exp_path):
                    return True
                raise FileNotFoundError(f'No experiment data found for dat{exp2hdf.datnum} at {os.path.abspath(exp_path)}')

    @classmethod
    def list_open_dats(cls):
        return cls.open_dats


get_dat = DatHandler().get_dat
get_dats = DatHandler().get_dats
