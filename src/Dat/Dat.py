import inspect
from typing import List, Tuple, Union, NamedTuple

from src import config as cfg
from src.CoreUtil import verbose_message
from src.Dat.Entropy import Entropy
from src.Dat.Logs import Logs
from src.Dat.Instruments import Instruments
import numpy as np
import src.Dat.PlottingFunctions as PF
import src.Dat.Datutil as DU


class Dat(object):
    """Overall Dat object which contains general information about dat, more detailed info should be put
    into a subclass. Everything in this overall class should be useful for 99% of dats

    Init only puts Dat in DF but doesn't save DF"""

    # def __new__(cls, *args, **kwargs):
    #     return object.__new__(cls)

    def __getattr__(self, name):  # __getattribute__ overrides all, __getattr__ overrides only missing attributes
        # Note: This affects behaviour of hasattr(). Hasattr only checks if getattr returns a value, not whether
        # attribute was defined previously.
        raise AttributeError(f'Attribute {name} does not exist. Maybe want to implement getting attrs from datPD here')

    def __setattr__(self, name, value):
        # region Verbose Dat __setattr__
        if cfg.verbose is True:
            verbose_message(
                f'in override setattr. Being called from {inspect.stack()[1][3]}, hasattr is {hasattr(self, name)}')
        # endregion
        if not hasattr(self, name) and inspect.stack()[1][3] != '__init__':  # Inspect prevents this override
            # affecting init
            # region Verbose Dat __setattr__
            if cfg.verbose is True:
                verbose_message(
                    'testing setattr override')  # TODO: implement writing change to datPD at same time, maybe with a check?
            # endregion

        else:
            super().__setattr__(name, value)

    def __init__(self, datnum: int, datname, infodict: dict, dfname='default'):
        """Constructor for dat"""
        try:
            dattype = infodict['dattypes']
        except KeyError:
            dattype = 'none'  # Can't check if str is in None, but can check if in 'none'
        self.datnum = datnum
        if 'datname' in infodict:
            self.datname = datname
        else:
            self.datname = 'base'

        self.Logs = Logs(infodict)
        self.Instruments = Instruments(infodict)
        self.Entropy = None  # type: Entropy

        # TODO: These should be classes inside of the overall class s.t. the dat object typing is not overcrowded
        if 'i_sense' in dattype:
            self.i_sense = infodict[
                'i_sense']  # type: np.ndarray  # Charge sensor current in nA  # TODO: Do I want to move this to a subclass?
        if 'entropy' in dattype:
            if 'enty' in infodict.keys():
                enty = infodict['enty']
            else:
                enty = None
            self.Entropy = Entropy(self, infodict['entx'], enty=enty)
            pass
        self.dfname = dfname

    def display(self, data, ax=None, xlabel: str = None, ylabel: str = None, swapax=False, norm=None, colorscale=True,
                axtext=None, **kwargs):
        """Just displays 1D or 2D data using x and y array of dat. Can pass in option kwargs"""
        x = self.Logs.x_array
        y = self.Logs.y_array
        if xlabel is None:
            xlabel = self.Logs.x_label
        if ylabel is None:
            ylabel = self.Logs.y_label
        if swapax is True:
            x = y
            y = self.Logs.x_array
            data = np.swapaxes(data, 0, 1)
        if axtext is None:
            axtext = f'Dat{self.datnum}'
        ax = PF.get_ax(ax)
        if self.Logs.dim == 2:
            PF.display_2d(x, y, data, ax, norm, colorscale, xlabel, ylabel, axtext=axtext, **kwargs)
        elif self.Logs.dim == 1:
            PF.display_1d(x, data, ax, xlabel, ylabel, axtext=axtext, **kwargs)
        else:
            raise ValueError('No value of "dim" present to determine which plotting to use')
        return ax

    def display1D_slice(self, data, yval, ax=None, xlabel: str = None, yisindex=False, fontsize=10, textpos=(0.1, 0.8),
                        **kwargs):
        """Returns 1D plot of 2D data (takes 2D data as input) and index of the y value used"""
        # TODO: make work for vertical slice
        ax = PF.get_ax(ax)
        if yisindex is False:
            idy, yval = DU.get_id_from_val(self.y_array, yval)
        else:
            idy = yval
            yval = self.y_array[idy]
        data = data[idy]
        if 'axtext' in kwargs.keys() and kwargs['axtext']:
            axtext = f'Dat={self.datnum}\n@{yval:.1f}mV'
            kwargs['axtext'] = axtext
        if 'textpos' in kwargs.keys() and kwargs['textpos']:
            kwargs['textpos'] = textpos
        self.display(data, ax, xlabel, **kwargs)
        return ax, idy

    def dac(self, num):
        return