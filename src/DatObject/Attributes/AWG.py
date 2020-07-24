from src.DatObject.Attributes.DatAttribute import DatAttribute
import numpy as np
from typing import Union, TYPE_CHECKING
import h5py
import logging
from src import HDF_Util as HDU
from src import CoreUtil as CU

if TYPE_CHECKING:
    from src.DatObject.Attributes.Logs import AWGtuple

logger = logging.getLogger(__name__)


class AWG(DatAttribute):
    group_name = 'AWG'
    version = '1.1'

    """
    Version changes:
        1.1 -- Make general get_single_wave_mask, and full wave mask. No need for specific square one
    """

    def __init__(self, hdf):
        super().__init__(hdf)
        self.info: Union[AWGtuple, None] = None
        self.AWs: Union[list, None] = None  # AWs as stored in HDF by exp (1 cycle with setpoints/samples)

        # Useful for Square wave part to know some things about scan stored in other areas of HDF
        self.x_array = None
        self.measure_freq = None

        self.get_from_HDF()

    @property
    def wave_duration(self):
        """Length of once cycle of the wave in seconds"""
        if self.measure_freq:
            return self.info.wave_len*self.measure_freq
        else:
            logger.info(f'measure_freq not set for AWG')

    @property
    def true_x_array(self):
        """The actual DAC steps of x_array"""
        if self.x_array is not None:
            return np.linspace(self.x_array[0], self.x_array[-1], self.info.num_steps)
        else:
            logger.info(f'x_array not set for AWG')

    @property
    def numpts(self):
        info = self.info
        return info.wave_len * info.num_cycles * info.num_steps

    def _set_default_group_attrs(self):
        super()._set_default_group_attrs()
        self.group.attrs['description'] = "Information about Arbitrary Wave Generator used for scan. \n" \
                                          "Also a place to store any AWG related data/results etc"

    def get_from_HDF(self):
        self.info = HDU.get_attr(self.group, 'Logs')  # Load NamedTuple in
        if self.info is not None:
            self.AWs = [self.group['AWs'].get(f'AW{k}') for k in self.info.outputs.keys()]
        data_group = self.hdf.get('Data', None)
        if data_group:
            x_array = data_group.get('Exp_x_array', None)
            if x_array:
                self.x_array = x_array[:]
        logs_group = self.hdf.get('Logs', None)
        if logs_group:
            fdac_group = logs_group.get('FastDACs', None)
            if fdac_group:
                self.measure_freq = fdac_group.attrs.get('MeasureFreq', None)

    def update_HDF(self):
        logger.warning(f'Update HDF does not have any affect with AWG attribute currently')

    def get_single_wave(self, num):
        """Returns a full single wave AW (with correct number of points for sample rate)"""
        if not self._check_wave_num(num): return None
        aw = self.AWs[num]
        return np.concatenate([np.ones(int(aw[1][i])) * aw[0][i] for i in range(aw.shape[1])])

    def get_full_wave(self, num):
        """Returns the full waveform output through the whole scan with the same num points as x_array"""
        aw = self.get_single_wave(num)
        return np.array(list(aw) * int(self.info.num_cycles) * int(self.info.num_steps))

    def get_single_wave_masks(self, num):
        """
        Returns single wave masks for v0_1, vp, v0_2, vm (where AW is v0, vP, v0, vm)
        Args:
            num (int): Which AW

        Returns:
            List[np.ndarray, np.ndarray, np.ndarray]: A list of arrays of masks for AW
        """
        self._check_wave_num(num, raise_error=True)
        aw = self.AWs[num]
        lens = aw[1].astype(int)
        # single_masks = [np.concatenate([np.ones(int(aw[1, i])) if i in idxs else np.zeros(int(aw[1, i])) for i in range(aw.shape[1])]) for idxs in
        #     [[0, 2], [1], [3]]]
        masks = np.zeros((len(lens), np.sum(lens)), dtype=np.float16)  # Make 1 cycle
        for i, m in enumerate(masks):
            s = np.sum(lens[:i])
            m[s:s+lens[i]] = 1
            m[np.where(m == 0)] = np.nan
        return masks
        # for sm in single_masks:
        #     sm[np.where(sm == 0)] = np.nan
        # return single_masks

    def get_full_wave_masks(self, num):
        """
        Returns full wave masks for AW#
        Args:
            num (int): Which AW

        Returns:
            np.ndarray: An array of masks for AW (i.e. for 4 step wave, first dimension will be 4)
        """
        single_masks = self.get_single_wave_masks(num)
        full_masks = np.tile(single_masks, self.info.num_cycles * self.info.num_steps)
        return full_masks

    def _check_wave_num(self, num, raise_error=False):
        if num not in self.info.outputs.keys():
            if raise_error is True:
                raise ValueError(f'{num} not in AWs, choose from {self.info.outputs.keys()}')
            else:
                logger.warning(f'{num} not in AWs, choose from {self.info.outputs.keys()}')
            return False
        return True

    def eval(self, x, wave_num=0):
        """Returns square wave output at x value(s)

        Args:
            x (Union[int,float,np.ndarray]): x value(s) to get heating for
            wave_num (int): Which AWG to evaluate (0 or 1)
        Returns:
            (Union[float, np.ndarray]): Returns either the single value, or array of values
        """
        if np.all(np.isclose(x, self.x_array)):  # If full wave, don't bother searching for points
            idx = np.arange(self.x_array.shape[-1])
        else:
            idx = np.array(CU.get_data_index(self.x_array, x))
        wave = self.get_full_wave(wave_num)
        return wave[idx]


def init_AWG(group, logs_group, data_group: h5py.Group):
    """Convert data from standardized experiment data to dat HDF
    Should be run after Logs is initialized so that we can reuse AWG info saved there

    Args:
        AWG_tuple (AWGtuple): From Logs (contains sweeplogs info)
        group (h5py.Group): AWG group in dat HDF
        AWs (Union[List[np.ndarray], np.ndarray]): Either single, or list of AWs from Exp HDF

    Returns:

    """
    wg = group.require_group('AWs')

    AWG_tuple = HDU.get_attr(logs_group, 'AWG', None)
    if AWG_tuple is None:
        raise RuntimeError(f'No "AWG" found in Logs group, need to initialized there first')

    # Get AWs from Exp_data and put in AWG/AWs
    for k in AWG_tuple.outputs.keys():
        wave = data_group.get(f'Exp_fdAW_{k}', None)
        if wave is None:
            logger.warning(f'fdAW_{k} was not found in HDF')
        else:
            wg[f'AW{k}'] = wave

    # Add AWG logs info to AWG section directly by copying group
    group.copy(logs_group['AWG'], group, 'Logs')

    group.file.flush()
