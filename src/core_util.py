import collections
from deprecation import deprecated
import json
import copy
import os
import functools
from typing import List, Dict, Tuple, Union, Protocol, Optional, Any, NamedTuple, Callable, Iterable
import h5py
from scipy.interpolate import interp2d
from scipy.signal import firwin, filtfilt
from pathlib import Path

import lmfit as lm
import numpy as np
import numbers
import pandas as pd
import logging
import scipy.interpolate as scinterp
import src.characters as Char
import datetime
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

logger = logging.getLogger(__name__)


process_pool = ProcessPoolExecutor()  # max_workers defaults to num_cpu on machine (or 61 max)
thread_pool = ThreadPoolExecutor()  # max_workers defaults to min(32, num_cpu*5)1


def get_project_root() -> Path:
    return Path(__file__).parent.parent


def get_full_path(path):
    """
    Get real path (i.e. replacing any shortcut links along the way)
    """
    if os.path.exists(path):
        return path
    else:
        new_path = os.path.realpath(path)
        if not os.path.exists(new_path):
            raise FileNotFoundError
        else:
            return new_path


def center_data(x: np.ndarray, data: np.ndarray, centers: Union[List[float], np.ndarray],
                method: str = 'linear', return_x: bool = False) -> Union[Tuple[np.ndarray, np.ndarray], np.ndarray]:
    """
    Centers data onto x_array. x is required to at least have the same spacing as original x to calculate relative
    difference between rows of data based on center values.

    Args:
        return_x (bool): Whether to return the new x_array as well as centered data
        method (str): Specifies the kind of interpolation as a string
            (‘linear’, ‘nearest’, ‘zero’, ‘slinear’, ‘quadratic’, ‘cubic’, ‘previous’, ‘next’)
        x (np.ndarray): x_array of original data
        data (np.ndarray): data to center
        centers (Union(list, np.ndarray)): Centers of data in real units of x

    Returns:
        np.ndarray, [np.ndarray]: Array of data with np.nan anywhere outside of interpolation, and optionally new
        x_array where average center has been subtracted
    """
    data = np.atleast_2d(data)
    centers = np.asarray(centers)
    avg_center = np.average(centers)
    nx = np.linspace(x[0] - avg_center, x[-1] - avg_center, data.shape[-1])
    ndata = []
    for row, center in zip(data, centers):
        interper = scinterp.interp1d(x - center, row, kind=method, assume_sorted=False, bounds_error=False)
        ndata.append(interper(nx))
    ndata = np.array(ndata)
    if return_x is True:
        return ndata, nx
    else:
        return ndata


def mean_data(x: np.ndarray, data: np.ndarray, centers: Union[List[float], np.ndarray],
              method: str = 'linear', return_x: bool = False, return_std: bool = False,
              nan_policy: str = 'omit') -> \
        Union[Tuple[np.ndarray, np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray], np.ndarray]:
    """
    Centers data and then calculates mean and optionally standard deviation from mean
    Args:
        x (np.ndarray):
        data (np.ndarray):
        centers (np.ndarray):
        method (str):
        return_x (bool):
        return_std (bool):
        nan_policy (str): 'omit' to leave NaNs in any column that has > 1 NaN, 'ignore' to do np.nanmean(...)
    Returns:
        np.ndarray, [np.ndarray]: data averaged along axis 0, optionally the centered x and/or the standard deviation of mean
    """
    temp_centered = center_data(x, data, centers, method, return_x=return_x)
    if return_x:
        centered, x = temp_centered
    else:
        centered = temp_centered
        x = None

    if nan_policy == 'omit':
        averaged = np.mean(centered, axis=0)
    elif nan_policy == 'ignore':
        averaged = np.nanmean(centered, axis=0)
    else:
        raise ValueError(f'got {nan_policy} for nan_policy. Must be "omit" or "ignore"')

    ret = [averaged]
    if return_x:
        ret.append(x)
    if return_std:
        ret.append(np.nanstd(data, axis=0))
    if len(ret) == 1:
        ret = ret[0]
    return ret


def get_data_index(data1d: Union[np.ndarray, list], val: Union[float, list, tuple, np.ndarray], is_sorted: bool=False) \
        -> Union[int, np.ndarray]:
    """
    Returns index position(s) of nearest data value(s) in 1d data.
    Args:
        is_sorted: If data1d is already sorted, set sorted = True to improve performance
        data1d: data to compare values
        val: value(s) to find index positions of

    Returns:
        index value(s)

    """

    def find_nearest_index(array, value):
        idx = np.searchsorted(array, value, side="left")
        if idx > 0 and (idx == len(array) or abs(value - array[idx - 1]) < abs(
                value - array[idx])):  # TODO: if abs doesn't work, use math.fabs
            return idx - 1
        else:
            return idx

    data = np.asanyarray(data1d)
    val = np.atleast_1d(np.asarray(val))
    nones = np.where(val == None)
    if nones[0].size != 0:
        val[nones] = np.nan  # Just to not throw errors, will replace with Nones before returning
    if data.ndim != 1:
        raise ValueError(f'{data.ndim} is not 1D')

    if is_sorted is False:
        arr_index = np.argsort(data)  # get copy of indexes of sorted data
        data = np.sort(data)  # Creates copy of sorted data
        index = arr_index[np.array([find_nearest_index(data, v) for v in val])]
    else:
        index = np.array([find_nearest_index(data, v) for v in val])
    index = index.astype('O')
    if nones[0].size != 0:
        index[nones] = None
    if index.shape[0] == 1:
        index = index[0]
    return index


def ensure_list(data) -> list:
    if type(data) == str:
        return [data]
    elif type(data) == list:
        return data
    elif type(data) == tuple:
        return list(data)
    else:
        return [data]


def ensure_set(data) -> set:
    if type(data) == set:
        return data
    else:
        return set(ensure_list(data))


def edit_params(params: Union[lm.Parameters, List[lm.Parameters]],
                param_name: Union[str, List[str]],
                value: Union[Optional[float], List[Optional[float]]] = None,
                vary: Union[Optional[float], List[Optional[float]]] = None,
                min_val: Union[Optional[float], List[Optional[float]]] = None,
                max_val: Union[Optional[float], List[Optional[float]]] = None) -> lm.Parameters:
    """
    Returns a copy of parameters with values unmodified unless specified
    Args:
        params (): single lm.Parameters instance
        param_name (): Which parameter(s) to vary
        value (): Value(s) to set
        vary (): Whether parameter(s) should be allowed to vary
        min_val (): Min bound of parameter(s)
        max_val (): Max bound of parameter(s)

    Returns:
        (lm.Parameters): New modified lm.Parameters
    """

    def _make_array(val):
        if val is None:
            val = as_array([None] * len(param_names))
        else:
            val = as_array(val)
            assert len(val) == len(param_names)
        return val

    def as_array(val):
        val = np.asarray(val)
        if val.ndim == 0:
            val = np.array([val])
        return val

    params = copy.deepcopy(params)
    param_names = as_array(param_name)

    values = _make_array(value)
    varys = _make_array(vary)
    min_vals = _make_array(min_val)
    max_vals = _make_array(max_val)

    for param_name, value, vary, min_val, max_val in zip(param_names, values, varys, min_vals, max_vals):
        if min_val is None:
            min_val = params[param_name].min
        if max_val is None:
            max_val = params[param_name].max
        if value is None:
            value = params[param_name].value
        if vary is None:
            vary = params[param_name].vary
        params[param_name].vary = vary
        params[param_name].value = value
        params[param_name].min = min_val
        params[param_name].max = max_val
    return params


def sig_fig(val, sf=5):
    """
    Rounds to given given significant figures - taken from https://stackoverflow.com/a/59888924/12620905

    @param val: int, float, array, of values to round. Handles np.nan,
    @param sf: How many significant figures to round to.
    """

    def sig_fig_array(val, sf):  # Does the actual rounding part of int, float, array
        x = np.asarray(val)
        x_positive = np.where(np.isfinite(x) & (x != 0), np.abs(x), 10 ** (sf - 1))
        mags = 10 ** (sf - 1 - np.floor(np.log10(x_positive)))
        return np.round(x * mags) / mags

    if not isinstance(val, (numbers.Number, pd.Series, pd.DataFrame, np.ndarray)):
        return val
    elif type(val) == bool:
        return val
    if isinstance(val, pd.DataFrame):
        val = copy.deepcopy(val)
        num_dtypes = (float, int)
        for col in val.columns:
            if val[col].dtype in num_dtypes:  # Don't try to apply to strings for example
                val[col] = val[col].apply(lambda x: sig_fig_array(x, sf))  # Apply sig fig function to column
        return val
    elif type(val) == int:
        return int(sig_fig_array(val, sf))  # cast back to int afterwards
    else:
        return sig_fig_array(val, sf).astype(np.float32)


def my_round(x: Union[float, int, np.ndarray, np.number],
             prec: int = 2,
             base: Union[float, int] = 1) -> Union[float, np.ndarray]:
    """
    https://stackoverflow.com/questions/2272149/round-to-5-or-other-number-in-python
    Rounds to nearest multiple of base with given precision
    Args:
        x ():
        prec (): Precision (decimal places)
        base (): Number to round to nearest of

    Returns:
        Union[float, np.ndarray]: Single value or array of values rounded
    """
    return (base * (np.array(x) / base).round()).round(prec)


def fit_info_to_df(fits, uncertainties=False, sf=4, index=None):
    """
    Takes list of fits and puts all fit params into a dataframe optionally with index labels. Also adds reduced chi sq

    @param fits: list of fit results
    @type fits: List[lm.model.ModelResult]
    @param uncertainties: whether to show +- uncertainty in table. If so, values in table will be strings to sig fig
    given. 2 will return uncertainties only in df.
    @type uncertainties: Union[bool, int]
    @param sf: how many sig fig to give values to if also showing uncertainties, otherwise full values
    @type sf: int
    @param index: list to use as index of dataframe
    @type index: List
    @return: dataframe of fit info with index and reduced chi square
    @rtype: pd.DataFrame
    """

    columns = ['index'] + list(fits[0].best_values.keys()) + ['reduced_chi_sq']
    if index is None or len(index) != len(fits):
        index = range(len(fits))
    if uncertainties == 0:
        data = [[ind] + list(fit.best_values.values()) + [fit.redchi] for i, (ind, fit) in enumerate(zip(index, fits))]
    elif uncertainties == 1:
        keys = fits[0].best_values.keys()
        data = [[ind] + [str(sig_fig(fit.params[key].value, sf)) + Char.PM + str(sig_fig(fit.params[key].stderr, 2))
                         for key in keys] + [fit.redchi] for i, (ind, fit) in enumerate(zip(index, fits))]
    elif uncertainties == 2:
        keys = fits[0].best_values.keys()
        data = [[ind] + [fit.params[key].stderr for key in keys] + [fit.redchi] for i, (ind, fit) in
                enumerate(zip(index, fits))]
    else:
        raise NotImplementedError
    return pd.DataFrame(data=data, columns=columns)


def ensure_params_list(params: Union[List[lm.Parameters], lm.Parameters], data: np.ndarray) -> List[lm.Parameters]:
    """
    Make sure params is a list of lm.Parameters which matches the y dimension of data if it is 2D

    @param params: possible params, list of params, list of 1 param
    @type params: Union[List[lm.Parameters], lm.Parameters]
    @param data: data going to be fit
    @type data: np.ndarray
    @return: list of params which is right length for data
    @rtype: List[lm.Parameters]
    """
    if isinstance(params, lm.Parameters):
        if data.ndim == 2:
            params = [params] * data.shape[0]
        elif data.ndim == 1:
            params = [params]
        else:
            raise NotImplementedError
    elif isinstance(params, list):
        if data.ndim == 1:
            if len(params) != 1:
                logger.info(f'Wrong length list of params. Only using first of parameters')
                params = [params[0]]
        elif data.ndim == 2:
            if len(params) != data.shape[0]:
                logger.info(f'Wrong length list of params. Making params list multiple of first param')
                params = [params[0]] * data.shape[0]
        else:
            raise NotImplementedError
    else:
        raise ValueError(f'[{params}] is not a supported parameter list/object')
    return params


@deprecated(details="Use bin_data_new instead")
def bin_data(data: Union[np.ndarray, List[np.ndarray]], bin_size: Union[float, int]):
    """
    Reduces size of dataset by binning data with given bin_size. Works for 1D, 2D or list of datasets
    @param data: Either single 1D or 2D data, or list of dataset
    @type data: Union[np.ndarray, List[np.ndarray]]
    @param bin_size: bin_size (will drop the last values that don't fit in bin)
    @type bin_size: Union[float, int]
    @return: list of binned datasets, or single binned dataset
    @rtype: Union[list[np.ndarray], np.ndarray]
    """

    def _bin_1d(d, bin1d):
        d = np.asarray(d)
        assert d.ndim == 1
        new_data = []
        s = 0
        while s + bin1d <= len(d):
            new_data.append(np.average(d[s:s + bin1d]))
            s += bin1d
        return np.array(new_data).astype(np.float32)

    def _bin_2d(d, bin2d):
        d = np.asarray(d)
        if d.ndim == 1:
            return _bin_1d(d, bin2d)
        elif d.ndim == 2:
            return np.array([_bin_1d(row, bin2d) for row in d])

    bin_size = int(bin_size)
    if bin_size <= 1:
        return data
    else:
        if isinstance(data, h5py.Dataset):
            data = data[:]
        if isinstance(data, (list, tuple)):  # Possible list of datasets
            if len(data) > bin_size * 10:  # Probably just a dataset that isn't an np.ndarray
                print(f'WARNING[CU.bin_data]: data passed in was a list with len [{len(data)}].'
                      f' Assumed this to be a 1D dataset rather than list of datasets.'
                      f' Making data an np.ndarray first will prevent this warning message in the future')
                return _bin_2d(data, bin_size)
            else:
                return [_bin_2d(data_set, bin_size) for data_set in data]
        elif isinstance(data, np.ndarray):
            if data.ndim not in [1, 2]:
                raise NotImplementedError(f'ERROR[CU.bin_data]:Only 1D or 2D data supported for binning.'
                                          f' Data passed had ndim = [{data.ndim}')
            else:
                return _bin_2d(data, bin_size)
        else:
            print(f'WARNING[CU.bin_data]: Bad datatype [{type(data)}] passed in. Returned None')
            return None


def get_bin_size(target: int, actual: int) -> int:
    """
    Returns bin size which will reduce from 'actual' numpnts to 'target' numpnts.
    Args:
        target (): Target num points after binning
        actual (): Num points before binning

    Returns:
        (int): Bin size s.t. final numpnts >= target
    """
    return int(np.ceil(actual/target))


def bin_data_new(data: np.ndarray, bin_x: int = 1, bin_y: int = 1, bin_z: int = 1) -> np.ndarray:
    """
    Bins up to 3D data in x then y then z. If bin_y == 1 then it will only bin in x direction (similar for z)
    )

    Args:
        data (np.ndarray): 1D, 2D or 3D data to bin in x and or y axis and or z axis
        bin_x (): Bin size in x
        bin_y (): Bin size in y
        bin_z (): Bin size in z
    Returns:

    """
    ndim = data.ndim
    data = np.array(data, ndmin=3)
    os = data.shape
    num_z, num_y, num_x = [np.floor(s / b).astype(int) for s, b in zip(data.shape, [bin_z, bin_y, bin_x])]
    # ^^ Floor so e.g. num_x*bin_x does not exceed len x
    chop_z, chop_y, chop_x = [s - n * b for s, n, b in zip(data.shape, [num_z, num_y, num_x], [bin_z, bin_y, bin_x])]
    # ^^ How much needs to be chopped off in total to make it a nice round number
    data = data[
           np.floor(chop_z / 2).astype(int): os[0] - np.ceil(chop_z / 2).astype(int),
           np.floor(chop_y / 2).astype(int): os[1] - np.ceil(chop_y / 2).astype(int),
           np.floor(chop_x / 2).astype(int): os[2] - np.ceil(chop_x / 2).astype(int)
           ]
    rs = data.shape
    data = data.reshape((rs[0], rs[1], num_x, bin_x)).mean(axis=3)
    data = data.reshape((rs[0], num_y, bin_y, num_x)).mean(axis=2)
    data = data.reshape((num_z, bin_z, num_y, num_x)).mean(axis=1)

    if ndim == 3:
        return data
    elif ndim == 2:
        return data[0]
    elif ndim == 1:
        return data[0, 0]
    return data


def resample_data(data: np.ndarray,
                  x: Optional[np.ndarray] = None,
                  y: Optional[np.ndarray] = None,
                  z: Optional[np.ndarray] = None,
                  max_num_pnts: int = 500,
                  resample_method: str = 'bin',
                  ):
    """
    Resamples either by binning or downsampling to reduce shape in all axes to below max_num_pnts.
    Will always return data, then optionally ,x, y, z incrementally (i.e. can do only x or only x, y but cannot do
    e.g. x, z)
    Args:
        data (): Data to resample down to < self.MAX_POINTS in each dimension
        x (): Optional x array to resample the same amount as data
        y (): Optional y ...
        z (): Optional z ...
        max_num_pnts: Max number of points after resampling
        resample_method: Whether to resample using binning 'bin' or downsampling 'downsample' (i.e. dropping data points)

    Returns:
        (Any): Matching combination of what was passed in (e.g. data, x, y ... or data only, or data, x, y, z)
    """

    def chunk_size(orig, desired):
        """chunk_size can be for binning or downsampling"""
        s = round(orig / desired)
        if orig > desired and s == 1:
            s = 2  # At least make sure it is sampled back below desired
        elif s == 0:
            s = 1  # Make sure don't set zero size
        return s

    def check_dim_sizes(data, x, y, z) -> bool:
        """If x, y, z are provided, checks that they match the corresponding data dimension"""
        for arr, expected_shape in zip([x, y, z], list(reversed(data.shape))):
            if arr is not None:
                if arr.shape[0] != expected_shape:
                    raise RuntimeError(f'data.shape: {data.shape}, (z, y, x).shape: '
                                       f'({[arr.shape if arr is not None else arr for arr in [z, y, x]]}). '
                                       f'at least one of x, y, z has the wrong shape (None is allowed)')
        return True

    data, x, y, z = [np.asanyarray(arr) if arr is not None else None for arr in [data, x, y, z]]
    check_dim_sizes(data, x, y, z)

    ndim = data.ndim
    data = np.array(data, ndmin=3)
    shape = data.shape
    if any([s > max_num_pnts for s in shape]):
        chunk_sizes = [chunk_size(s, max_num_pnts) for s in reversed(shape)]  # (shape is z, y, x otherwise)
        if resample_method == 'bin':
            data = bin_data_new(data, *chunk_sizes)
            x, y, z = [bin_data_new(arr, cs) if arr is not None else arr for arr, cs in zip([x, y, z], chunk_sizes)]
        elif resample_method == 'downsample':
            data = data[::chunk_sizes[-1], ::chunk_sizes[-2], ::chunk_sizes[-3]]
            x, y, z = [arr[::cs] if arr is not None else None for arr, cs in zip([x, y, z], chunk_sizes)]
        else:
            raise ValueError(f'{resample_method} is not a valid option')

    if ndim == 1:
        data = data[0, 0]
        if x is not None:
            return data, x
        return data

    elif ndim == 2:
        data = data[0]
        if x is not None:
            if y is not None:
                return data, x, y
            return data, x
        return data

    elif ndim == 3:
        if x is not None:
            if y is not None:
                if z is not None:
                    return data, x, y, z
                return data, x, y
            return data, x
        return data
    raise ValueError(f'Most likely something wrong with {data}')


def remove_nans(nan_data, other_data=None, verbose=True):
    """Removes np.nan values from 1D or 2D data, and removes corresponding values from 'other_data' if passed
    other_data can be 1D even if nan_data is 2D"""
    assert isinstance(nan_data, (np.ndarray, pd.Series))
    nan_data = np.atleast_2d(nan_data).astype(np.float32)
    if other_data is not None:
        assert isinstance(other_data, (np.ndarray, pd.Series, h5py.Dataset))
        other_data = np.atleast_2d(other_data)
        assert nan_data.shape[1] == other_data.shape[1]
    mask = ~np.isnan(nan_data)
    if not np.all(mask[0] == mask):
        raise ValueError(
            'Trying to mask data which has different NaNs per row. To achieve that iterate through 1D slices')
    mask = mask[0]  # Only need first row of it now
    nans_removed = nan_data.shape[1] - np.sum(mask)
    if nans_removed > 0 and verbose:
        logger.info(f'Removed {nans_removed} np.nans (per row)')
    ndata = np.squeeze(nan_data[:, mask])
    if other_data is not None:
        odata = np.squeeze(other_data[:, mask])
        return ndata, odata
    else:
        return ndata


def get_nested_attr_default(obj, attr_path, default):
    """Trys getting each attr separated by . otherwise returns default
    @param obj: object to look for attributes in
    @param attr_path: attribute path to look for (e.g. "Logs.x_label")
    @type attr_path: str
    @param default: value to default to in case of error or None
    @type default: any
    @return: Value of attr or default
    @rtype: any
    """
    attrs = attr_path.split('.')
    val = obj
    for attr in attrs:
        val = getattr(val, attr, None)
        if val is None:
            break
    if val is None:
        return default
    else:
        return val


def order_list(l, sort_by: list = None) -> list:
    """Returns list of in increasing order using sort_by list or just sorting itself"""
    if sort_by is None:
        ordered = sorted(l)
    else:
        arr = np.array(l)
        sb = np.array(sort_by)
        return list(arr[sb.argsort()])
    return ordered


def FIR_filter(data, measure_freq, cutoff_freq=10.0, edge_nan=True, n_taps=101, plot_freq_response=False):
    """Filters 1D or 2D data and returns NaNs at edges

    Args:
        data ():
        measure_freq ():
        cutoff_freq ():
        edge_nan ():
        n_taps ():
        plot_freq_response ():

    Returns:

    """

    def plot_response(b, mf, co):
        """Plots frequency response of FIR filter base on taps(b) (could be adapted to IIR by adding a where 1.0 is"""
        from scipy.signal import freqz
        import matplotlib.pyplot as plt
        w, h = freqz(b, 1.0, worN=1000)
        fig, ax = plt.subplots(1)
        ax: plt.Axes
        ax.plot(0.5 * mf * w / np.pi, np.abs(h), 'b')
        ax.plot(co, 0.5 * np.sqrt(2), 'ko')
        ax.set_xlim(0, 0.5 * mf)
        ax.set_title("Lowpass Filter Frequency Response")
        ax.set_xlabel('Frequency [Hz]')
        ax.set_yscale('log')
        ax.grid()

    # Nyquist frequency
    nyq_rate = measure_freq / 2.0
    if data.shape[-1] < n_taps * 10:
        N = round(data.shape[0] / 10)
    else:
        N = n_taps
    # Create lowpass filter with firwin and hanning window
    taps = firwin(N, cutoff_freq / nyq_rate, window='hanning')

    # This is just in case I want to change the filter characteristics of this filter. Easy place to see what it's doing
    if plot_freq_response:
        plot_response(taps, measure_freq, cutoff_freq)

    # Use filtfilt to filter data with FIR filter
    filtered = filtfilt(taps, 1.0, data, axis=-1)
    if edge_nan:
        filtered = np.atleast_2d(filtered)  # So will work on 1D or 2D
        filtered[:, :N - 1] = np.nan
        filtered[:, -N - 1:] = np.nan
        filtered = np.squeeze(filtered)  # Put back to 1D or leave as 2D
    return filtered


def decimate(data, measure_freq, desired_freq=None, decimate_factor=None, numpnts=None, return_freq=False):
    """ Decimates 1D or 2D data by filtering at 0.5 decimated data point frequency and then down sampling. Edges of
    data will have NaNs due to filtering

    Args:
        data (np.ndarray): 1D or 2D data to decimate
        measure_freq (float): Measure frequency of data points
        desired_freq (float): Rough desired frequency of data points after decimation - Note: it will be close to this but
        not exact
        decimate_factor (int): How much to divide datapoints by (e.g. 2 reduces data point frequency by factor of 2)
        numpnts (int): Target number of points after decimation (use either this, desired_freq, or decimate_factor)
        return_freq (bool): Whether to also return the new true data point frequency or not

    Returns:
        Union(np.ndarray, Tuple[np.ndarray, float]): If return_freq is False, then only decimated data will be returned
        with NaNs on each end s.t. np.linspace(x[0], x[-1], data.shape[-1]) will match up correctly.
        If return_freq  is True, additionally the new data point frequency will be returned.
    """
    if (desired_freq and decimate_factor and numpnts) or (
            desired_freq is None and decimate_factor is None and numpnts is None):
        raise ValueError(f'Supply either decimate factor OR desire_freq OR numpnts')
    if desired_freq:
        decimate_factor = round(measure_freq / desired_freq)
    elif numpnts:
        decimate_factor = int(np.ceil(data.shape[-1] / numpnts))

    if decimate_factor < 2:
        logger.warning(f'Decimate factor = {decimate_factor}, must be 2 or greater, original data returned')
        return data

    true_freq = measure_freq / decimate_factor
    cutoff = true_freq / 2
    ntaps = 5 * decimate_factor  # Roughly need more to cut off at lower fractions of original to get good roll-off
    if ntaps > 2000:
        logger.warning(f'Reducing measure_freq={measure_freq:.1f}Hz to {true_freq:.1f}Hz requires ntaps={ntaps} '
                       f'in FIR filter, which is a lot. Using 2000 instead')
        ntaps = 2000  # Will get very slow if using too many
    elif ntaps < 21:
        ntaps = 21

    nz = FIR_filter(data, measure_freq, cutoff, edge_nan=True, n_taps=ntaps)
    nz = np.squeeze(np.atleast_2d(nz)[:, ::decimate_factor])  # To work on 1D or 2D data
    if return_freq:
        return nz, true_freq
    else:
        return nz


def get_matching_x(original_x, data_to_match: Optional[np.ndarray] = None, shape_to_match: Optional[int] = None):
    """Just returns linearly spaced x values between original_x[0+bin/2] and original_x[-1-bin/2] with same last axis
    shape as data.
    Note: bin size is guessed by comparing sizes of orig_x and data
    """
    if data_to_match is not None:
        new_len = data_to_match.shape[-1]
    elif shape_to_match is not None:
        new_len = shape_to_match
    else:
        raise ValueError(f'Pass in at least one of "data_to_match" or "shape_to_match"')
    half_bin = round(original_x.shape[-1] / (2 * new_len))
    return np.linspace(original_x[0 + half_bin], original_x[-1 - half_bin], new_len)


def get_sweeprate(measure_freq, x_array: Union[np.ndarray, h5py.Dataset]):
    dx = np.mean(np.diff(x_array))
    mf = measure_freq
    return mf * dx


def numpts_from_sweeprate(sweeprate, measure_freq, start, fin):
    return round(abs(fin - start) * measure_freq / sweeprate)


class DataClass(Protocol):
    """Defines what constitutes a dataclasses dataclass for type hinting only"""
    __dataclass_fields__: Dict


def interpolate_2d(x, y, z, xnew, ynew, **kwargs):
    """
    Interpolates 2D data returning NaNs where NaNs in original data.
    Taken from https://stackoverflow.com/questions/51474792/2d-interpolation-with-nan-values-in-python
    Scipy.interp2d by itself doesn't handle NaNs (and isn't documented!!)
    Args:
        x (np.ndarray):
        y (np.ndarray):
        z (np.ndarray):
        xnew (np.ndarray):
        ynew (np.ndarray):
        **kwargs (dict):

    Returns:
        np.ndarray: interpolated data
    """
    nan_map = np.zeros_like(z)
    nan_map[np.isnan(z)] = 1

    filled_z = z.copy()
    filled_z[np.isnan(z)] = 0

    f = interp2d(x, y, filled_z, **kwargs)
    f_nan = interp2d(x, y, nan_map, **kwargs)

    z_new = f(xnew, ynew)
    nan_new = f_nan(xnew, ynew)
    z_new[nan_new > 0.1] = np.nan
    return z_new


# def run_concurrent(funcs, func_args=None, func_kwargs=None, which='multiprocess', max_num=10):
#     which = which.lower()
#     if which not in ('multiprocess', 'multithread'):
#         raise ValueError('Which must be "multiprocess" or "multithread"')
#
#     if type(funcs) != list and type(func_args) == list:
#         funcs = [funcs] * len(func_args)
#     if func_args is None:
#         func_args = [[]] * len(funcs)
#     else:
#         # Make sure func_args is a list of lists, (for use with list of single args)
#         for i, arg in enumerate(func_args):
#             if type(arg) not in [list, tuple]:
#                 func_args[i] = [arg]
#     if func_kwargs is None:
#         func_kwargs = [{}] * len(funcs)
#
#     num_workers = len(funcs)
#     if num_workers > max_num:
#         num_workers = max_num
#
#     results = {i: None for i in range(len(funcs))}
#
#     if which == 'multithread':
#         worker_maker = concurrent.futures.ThreadPoolExecutor
#     elif which == 'multiprocess':
#         worker_maker = concurrent.futures.ProcessPoolExecutor
#     else:
#         raise ValueError
#
#     with worker_maker(max_workers=num_workers) as executor:
#         future_to_result = {executor.submit(func, *f_args, **f_kwargs): i for i, (func, f_args, f_kwargs) in
#                             enumerate(zip(funcs, func_args, func_kwargs))}
#         for future in concurrent.futures.as_completed(future_to_result):
#             i = future_to_result[future]
#             results[i] = future.result()
#     return list(results.values())


# class MyLRU2:
#     """
#     Acts like an LRU cache, but allows access to the cache to delete entries for example
#     Use as a decorator e.g. @MyLRU (then def... under that)
#
#     Adapted from https://pastebin.com/LDwMwtp8
#     I added update_wrapper, and __repr__ override to make wrapped functions look more like original function.
#     Also added **kwargs support, and some cache_remove/replace methods
#     """
#
#     def __init__(self, func, maxsize=128):
#         self.cache = collections.OrderedDict()
#         self.func = func
#         self.maxsize = maxsize
#         functools.update_wrapper(self, self.func)
#
#     def __call__(self, *args, **kwargs):
#         cache = self.cache
#         key = self._generate_hash_key(*args, **kwargs)
#         if key in cache:
#             cache.move_to_end(key)
#             return cache[key]
#         result = self.func(*args, **kwargs)
#         cache[key] = result
#         if len(cache) > self.maxsize:
#             cache.popitem(last=False)
#         return result
#
#     def __repr__(self):
#         return self.func.__repr__()
#
#     def clear_cache(self):
#         self.cache.clear()
#
#     def cache_remove(self, *args, **kwargs):
#         """Remove an item from the cache by passing the same args and kwargs"""
#         key = self._generate_hash_key(*args, **kwargs)
#         if key in self.cache:
#             self.cache.pop(key)
#
#     def cache_replace(self, value, *args, **kwargs):
#         key = self._generate_hash_key(*args, **kwargs)
#         self.cache[key] = value
#
#     @staticmethod
#     def _generate_hash_key(*args, **kwargs):
#         key = hash(args) + hash(frozenset(sorted(kwargs.items())))
#         return key


def MyLRU(func, wrapping_method=True, maxsize=128):
    """
    Acts like an LRU cache, but allows access to the cache to delete entries for example
    Use as a decorator e.g. @MyLRU (then def... under that)

    Adapted from https://pastebin.com/LDwMwtp8 -- There it was a Class, but I found that the __call__(self...) removed
    the self argument when wrapped around methods of a class. I'm not sure if there is any downside to just
    assigning 'methods' to the wrapper compared to the wrapper being a class itself.

    Also added **kwargs support, and some cache_remove/replace methods
    """
    cache = collections.OrderedDict()

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if wrapping_method:
            key = _generate_hash_key(*args[1:], **kwargs)
        else:
            key = _generate_hash_key(*args, **kwargs)

        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        result = func(*args, **kwargs)
        cache[key] = result
        if len(cache) > maxsize:
            cache.popitem(last=False)
        return result

    def cache_clear():
        cache.clear()

    def cache_remove(*args, **kwargs):
        """Remove an item from the cache by passing the same args and kwargs"""
        key = _generate_hash_key(*args, **kwargs)
        if key in cache:
            cache.pop(key)

    def cache_replace(value, *args, **kwargs):
        key = _generate_hash_key(*args, **kwargs)
        cache[key] = value

    def _generate_hash_key(*args, **kwargs):
        # key = hashlib.md5(json.dumps(args).encode())
        # key.update(json.dumps(frozenset(sorted((kwargs.items())))).encode())
        key = hash(args) + hash(frozenset(sorted(kwargs.items())))
        # return key.hexdigest()
        return key

    wrapper.cache_clear = cache_clear
    wrapper.cache_remove = cache_remove
    wrapper.cache_replace = cache_replace
    # wrapper.wrapped_func = func
    return wrapper


def my_partial(func, *args, arg_start=1, **kwargs):
    """Similar to functools.partial but with more control over which args are replaced

    Note: arg_start is 1 by default NOT zero. Because this is usually useful for methods of classes.
    """

    @functools.wraps(func)
    def newfunc(*fargs, **fkwargs):
        new_kwargs = {**kwargs, **fkwargs}
        new_args = list(fargs[:arg_start])  # called args until fixed args at arg_start
        new_args.extend(args)  # Add fixed args
        new_args.extend(fargs[arg_start + len(args) - 1:])  # Add any remaining called args
        # print(f'args={args}, kwargs={kwargs}, fargs={fargs}, fkwargs={fkwargs}, new_args={new_args}, new_kwargs={new_kwargs}')
        return func(*new_args, **new_kwargs)

    # To make it more similar to functools.partial
    newfunc.func = func
    newfunc.args = args
    newfunc.arg_start = arg_start  # Might as well store this
    newfunc.keywords = kwargs
    return newfunc


def time_from_str(time_str: str):
    """Inverse of datetime.datetime().strftime()"""
    return datetime.datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f')


def nested_dict_val(d: dict, path: str, value: Optional[Union[dict, Any]] = None, mode: str = 'get'):
    """
    For getting, setting, popping nested dict values.
    Note: for getting better to use 'dictor' from import dictor
    Note: d is modified
    Args:
        d (): Dict to look in/modify
        path (): '.' separated path to dict values
        value (): Value to set if mode == 'set'
        mode (): Whether to get, set, or pop

    Returns:
        (Any): Either get value, pop value or None if setting. Note: d is modified also
    """
    keys = path.split('.')
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    if mode == 'set':
        d[keys[-1]] = value
    elif mode == 'get':
        return d[keys[-1]]
    elif mode == 'pop':
        return d.pop(keys[-1])
    else:
        raise ValueError(f'{mode} not an acceptable mode')


def data_to_NamedTuple(data: dict, named_tuple) -> NamedTuple:
    """Given dict of key: data and a named_tuple with the same keys, it returns the filled NamedTuple"""
    tuple_dict = named_tuple.__annotations__  # Get ordered dict of keys of namedtuple
    for key in tuple_dict.keys():  # Set all values to None so they will default to that if not entered
        tuple_dict[key] = None
    for key in set(data.keys()) & set(tuple_dict.keys()):  # Enter valid keys values
        tuple_dict[key] = data[key]
    if set(data.keys()) - set(tuple_dict.keys()):  # If there is something left behind
        logger.warning(f'data keys not stored: {set(data.keys()) - set(tuple_dict.keys())}')
    ntuple = named_tuple(**tuple_dict)
    return ntuple


def json_dumps(dict_: dict):
    """Converts dictionary to json string, and has some added conversions for numpy objects etc"""

    def convert(o):
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError

    return json.dumps(dict_, default=convert)


def run_multiprocessed(func: Callable, datnums: Iterable[int]) -> Any:
    """
    Run 'func' on all processors of machine. 'func' must take datnum only (i.e. load the dat inside the function)
    Multiple calls to this function will always use the same process pool, so it should prevent creating too many
    processes

    Note: Use this for CPU bound tasks

    Args:
        func (): Any function which takes 'datnum' only as an argument. Results will be returned in order
        datnums (): Any iterable of datnums to do the processing on

    Returns:
        (Any): Returns whatever the func returns for each datnum in order
    """
    return list(process_pool.map(func, datnums))


def run_multithreaded(func: Callable, datnums: Iterable[int]) -> Any:
    """
    Run 'func' on ~30 threads (depends on num processors of machine). 'func' must take datnum only
    (i.e. load the dat inside the function). Multiple calls to this function will always use the same thread pool,
    so it should prevent creating too many threads

    Note: Use this for I/O bound tasks

    Args:
        func (): Any function which takes 'datnum' only as an argument. Results will be returned in order
        datnums (): Any iterable of datnums to do the processing on

    Returns:
        (Any): Returns whatever the func returns for each datnum in order
    """
    return list(thread_pool.map(func, datnums))


def data_row_name_append(data_rows: Optional[Tuple[Optional[int], Optional[int]]]) -> str:
    """String to name of data for selected rows only"""
    if data_rows is not None and not all(v is None for v in data_rows):
        return f':Rows[{data_rows[0]}:{data_rows[1]}]'
    else:
        return ''