"""
This is where all general dat plotting functions should live... To use in other pages, import the more general plotting
function from here, and make a little wrapper plotting function which calls with the relevant arguments
"""
from __future__ import annotations
from src.UsefulFunctions import bin_data_new, get_matching_x
from src.CoreUtil import get_nested_attr_default

import plotly.graph_objects as go
import numpy as np
import logging
import abc
from typing import Optional, Union, List, Tuple, Dict, Any
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.DatObject.DatHDF import DatHDF

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class DatPlotter(abc.ABC):
    """Generally useful functions for all Dat Plotters"""

    MAX_POINTS = 1000  # Maximum number of points to plot in x or y
    RESAMPLE_METHOD = 'bin'  # Whether to resample down to 1000 points by binning or just down sampling (i.e every nth)

    def __init__(self, dat: Optional[DatHDF] = None, dats: Optional[List[DatHDF]] = None):
        """Initialize with a dat or dats to provide some ability to get defaults"""
        if dat:
            self.dat = dat
        elif dats:
            self.dat = dats[0]
        else:
            self.dat = dat
            logger.warning(f'No Dat supplied, no values will be supplied by default')
        self.dats = dats

    def figure(self,
               xlabel: Optional[str] = None, ylabel: Optional[str] = None,
               title: Optional[str] = None,
               fig_kwargs: Optional[dict] = None) -> go.Figure:
        """
        Generates a go.Figure only using defaults from dat where possible.
        Use this as a starting point to add multiple traces. Or if only adding one trace, use 'plot' instead.
        Args:
            xlabel (): X label for figure
            ylabel (): Y label for figure
            title (): Title for figure
            fig_kwargs (): Other fig_kwargs which are accepted by go.Figure()

        Returns:
            (go.Figure): Figure without any data, only axis labels and title etc.
        """
        if fig_kwargs is None:
            fig_kwargs = {}

        xlabel = self._get_xlabel(xlabel)
        ylabel = self._get_ylabel(ylabel)

        fig = go.Figure(**fig_kwargs)
        fig.update_layout(xaxis_title=xlabel, yaxis_title=ylabel, title=title)
        return fig

    @abc.abstractmethod
    def plot(self, trace_kwargs: Optional[dict], fig_kwargs: Optional[dict]) -> go.Figure:
        """Override to make something which returns a competed plotly go.Figure

        Note: Should also include: trace_kwargs: Optional[dict] = None, fig_kwargs: Optional[dict] = None
        """
        pass

    @abc.abstractmethod
    def trace(self, trace_kwargs: Optional[dict]) -> go.Trace:
        """Override to make something which returns the completed trace only

        Note: Should also include: trace_kwargs: Optional[dict] = None
        """
        pass

    def add_textbox(self, fig: go.Figure, text: str, position: Union[str, Tuple[float, float]],
                    fontsize=10):
        """
        Adds <text> to figure in a text box.
        Args:
            fig (): Figure to add text box to
            text (): Text to add
            position (): Absolute position on figure to add to (e.g. (0.5,0.9) for center top, or 'CT' for center top, or 'T' for center top)

        Returns:
            None
        """
        if isinstance(position, str):
            position = get_position_from_string(position)
        text = text.replace('\n', '<br>')
        fig.add_annotation(text=text,
                           xref='paper', yref='paper',
                           x=position[0], y=position[1],
                           showarrow=False,
                           bordercolor='#111111',
                           borderpad=3,
                           borderwidth=1,
                           opacity=0.8,
                           bgcolor='#F5F5F5',
                           font=dict(size=fontsize)
                           )

    def add_line(self, fig: go.Figure, value: float, mode: str = 'horizontal',
                 color: Optional[str] = None) -> go.Figure:
        """
        Convenience for adding a line to a graph
        Args:
            fig (): Figure to add line to
            value (): Where to put line
            mode (): horizontal or vertical
            color(): Color of line

        Returns:
            (go.Figure): Returns original figure with line added
        """
        def _add_line(x0, x1, xref, y0, y1, yref):
            fig.add_shape(dict(y0=y0, y1=y1, yref=yref, x0=x0, x1=x1, xref=xref,
                               type='line',
                               line=dict(color=color),
                               ))

        def add_vertical(x):
            _add_line(x0=x, x1=x, xref='x', y0=0, y1=1, yref='paper')

        def add_horizontal(y):
            _add_line(x0=0, x1=1, xref='paper', y0=y, y1=y, yref='y')

        if mode == 'horizontal':
            add_horizontal(y=value)
        elif mode == 'vertical':
            add_vertical(x=value)
        else:
            raise NotImplementedError(f'{mode} not recognized')
        return fig

    def save_to_dat(self, fig, name: Optional[str] = None, sub_group_name: Optional[str] = None, overwrite: bool = False):
        """Saves to the Figures attribute of the dat"""
        self.dat.Figures.save_fig(fig, name=name, sub_group_name=sub_group_name, overwrite=overwrite)

    def _resample_data(self, data: np.ndarray,
                       x: Optional[np.ndarray] = None,
                       y: Optional[np.ndarray] = None,
                       z: Optional[np.ndarray] = None):
        """
        Resamples given data using self.MAX_POINTS and self.RESAMPLE_METHOD.
        Will always return data, then optionally ,x, y, z incrementally (i.e. can do only x or only x, y but cannot do
        e.g. x, z)
        Args:
            data (): Data to resample down to < self.MAX_POINTS in each dimension
            x (): Optional x array to resample the same amount as data
            y (): Optional y ...
            z (): Optional z ...

        Returns:
            (Any): Matching combination of what was passed in (e.g. data, x, y ... or data only, or data, x, y, z)
        """
        def chunk_size(orig, desired):
            """chunk_size can be for binning or downsampling"""
            s = round(orig/desired)
            if orig > desired and s == 1:
                s = 2  # At least make sure it is sampled back below desired
            elif s == 0:
                s = 1  # Make sure don't set zero size
            return s

        def check_dim_sizes(data, x, y, z) -> bool:
            """If x, y, z are provided, checks that they match the corresponding data dimension"""
            for arr, expected_shape in zip([z, y, x], data.shape):
                if arr is not None:
                    if arr.shape[0] != expected_shape:
                        raise RuntimeError(f'data.shape: {data.shape}, (z, y, x).shape: '
                                           f'({[arr.shape if arr is not None else arr for arr in [z, y, x]]}). '
                                           f'at least one of x, y, z has the wrong shape (None is allowed)')
            return True

        check_dim_sizes(data, x, y, z)

        ndim = data.ndim
        data = np.array(data, ndmin=3)
        shape = data.shape
        if any([s > self.MAX_POINTS for s in shape]):
            chunk_sizes = [chunk_size(s, self.MAX_POINTS) for s in reversed(shape)]  # (shape is z, y, x otherwise)
            if self.RESAMPLE_METHOD == 'bin':
                data = bin_data_new(data, *chunk_sizes)
                x, y, z = [bin_data_new(arr, cs) if arr is not None else arr for arr, cs in zip([x, y, z], chunk_sizes)]
            elif self.RESAMPLE_METHOD == 'downsample':
                data = data[::chunk_sizes[-1], ::chunk_sizes[-2], ::chunk_sizes[-3]]
                x, y, z = [arr[::cs] if arr is not None else None for arr, cs in zip([x, y, z], chunk_sizes)]
            else:
                raise ValueError(f'{self.RESAMPLE_METHOD} is not a valid option')

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

    # Get values from dat if value passed in is None
    # General version first, then specific ones which will be used more frequently
    def _get_any(self, any_name: str, any_value: Optional[Any] = None):
        """Can use this to get any value from dat by passing a '.' separated string path to the attr
        Note: will default to None if not found instead of raising error
        'any_value' will be returned if it is not None.
        """
        if any_value is None and self.dat:
            return get_nested_attr_default(self.dat, any_name, None)
        return any_value

    def _get_x(self, x):
        if x is None and self.dat:
            return self.dat.Data.x
        return x

    def _get_y(self, y):
        if y is None and self.dat:
            return self.dat.Data.y
        return y

    def _get_xlabel(self, xlabel):
        if xlabel is None and self.dat:
            return self.dat.Logs.xlabel
        return xlabel

    def _get_ylabel(self, ylabel):
        if ylabel is None and self.dat:
            return self.dat.Logs.ylabel
        return ylabel


class OneD(DatPlotter):
    """
    For 1D plotting
    """

    def trace(self, data: np.ndarray, x: Optional[np.ndarray] = None,
              mode: Optional[str] = None,
              name: Optional[str] = None,
              trace_kwargs: Optional[dict] = None) -> go.Scatter:
        """Just generates a trace for a figure"""
        if data.ndim != 1:
            raise ValueError(f'data.shape: {data.shape}. Invalid shape, should be 1D for a 1D trace')

        if trace_kwargs is None:
            trace_kwargs = {}
        x = self._get_x(x)
        mode = self._get_mode(mode)

        data, x = self._resample_data(data, x)  # Makes sure not plotting more than self.MAX_POINTS in any dim

        if data.shape != x.shape or x.ndim > 1 or data.ndim > 1:
            raise ValueError(f'Trying to plot data with different shapes or dimension > 1. '
                             f'(x={x.shape}, data={data.shape} for dat{self.dat.datnum}.')

        trace = go.Scatter(x=x, y=data, mode=mode, name=name, **trace_kwargs)
        return trace

    def plot(self, data: np.ndarray, x: Optional[np.ndarray] = None,
             xlabel: Optional[str] = None, ylabel: Optional[str] = None,
             trace_name: Optional[str] = None,
             title: Optional[str] = None,
             mode: Optional[str] = None,
             trace_kwargs: Optional[dict] = None, fig_kwargs: Optional[dict] = None) -> go.Figure:
        """Creates a figure and adds trace to it"""
        fig = self.figure(xlabel=xlabel, ylabel=ylabel,
                          title=title,
                          fig_kwargs=fig_kwargs)
        trace = self.trace(data=data, x=x, mode=mode, name=trace_name, trace_kwargs=trace_kwargs)
        fig.add_trace(trace)
        self._default_autosave(fig, name=title)
        return fig

    def _get_mode(self, mode):
        if mode is None:
            mode = 'markers'
        return mode

    def _get_ylabel(self, ylabel):
        if ylabel is None:
            ylabel = 'Arbitrary'
        return ylabel

    def _default_autosave(self, fig: go.Figure, name: Optional[str] = None):
        self.save_to_dat(fig, name=name)


class TwoD(DatPlotter):
    """
    For 2D plotting
    """

    def plot(self, data: np.ndarray, x: Optional[np.ndarray] = None, y: Optional[np.ndarray] = None,
             xlabel: Optional[str] = None, ylabel: Optional[str] = None,
             title: Optional[str] = None,
             plot_type: Optional[str] = None,
             trace_kwargs: Optional[dict] = None, fig_kwargs: Optional[dict] = None):
        if fig_kwargs is None:
            fig_kwargs = {}
        if plot_type is None:
            plot_type = 'heatmap'
        xlabel = self._get_xlabel(xlabel)
        ylabel = self._get_ylabel(ylabel)

        fig = go.Figure(self.trace(data=data, x=x, y=y, trace_type=plot_type, trace_kwargs=trace_kwargs), **fig_kwargs)
        fig.update_layout(xaxis_title=xlabel, yaxis_title=ylabel, title=title)
        self._plot_autosave(fig, name=title)
        return fig

    def trace(self, data: np.ndarray, x: Optional[np.ndarray] = None, y: Optional[np.ndarray] = None,
              trace_type: Optional[str] = None,
              trace_kwargs: Optional[dict] = None):
        if data.ndim != 2:
            raise ValueError(f'data.shape: {data.shape}. Invalid shape, should be 2D for a 2D trace')
        if trace_type is None:
            trace_type = 'heatmap'
        if trace_kwargs is None:
            trace_kwargs = {}
        x = self._get_x(x)
        y = self._get_y(y)

        logger.debug(f'data.shape: {data.shape}, x.shape: {x.shape}, y.shape: {y.shape}')
        data, x = self._resample_data(data, x)  # Makes sure not plotting more than self.MAX_POINTS in any dim

        if trace_type == 'heatmap':
            trace = go.Heatmap(x=x, y=y, z=data, **trace_kwargs)
        elif trace_type == 'waterfall':
            trace = [go.Scatter3d(mode='lines', x=x, y=[yval]*len(x), z=row, name=f'{yval:.3g}', **trace_kwargs) for row, yval in zip(data, y)]
        else:
            raise ValueError(f'{trace_type} is not a recognized trace type for TwoD.trace')
        return trace

    def _plot_autosave(self, fig: go.Figure, name: Optional[str] = None):
        self.save_to_dat(fig, name=name)


class ThreeD(DatPlotter):
    """
    For 3D plotting
    """

    def plot(self, trace_kwargs: Optional[dict] = None, fig_kwargs: Optional[dict] = None) -> go.Figure:
        pass

    def trace(self, trace_kwargs: Optional[dict] = None) -> go.Trace:
        # data, x = self._resample_data(data, x)  # Makes sure not plotting more than self.MAX_POINTS in any dim
        # if data.ndim != 3:
        #     raise ValueError(f'data.shape: {data.shape}. Invalid shape, should be 3D for a 3D trace')
        pass


def get_position_from_string(text_pos: str) -> Tuple[float, float]:
    assert isinstance(text_pos, str)
    ps = dict(C = 0.5, B=0.1, T=0.9, L=0.1, R=0.9)

    text_pos = text_pos.upper()
    if not all([l in ps for l in text_pos]) or len(text_pos) not in [1, 2]:
        raise ValueError(f'{text_pos} is not a valid position. It must be 1 or 2 long, with only {ps.keys()}')

    if len(text_pos) == 1:
        if text_pos == 'C':
            position = (ps['C'], ps['C'])
        elif text_pos == 'B':
            position = (ps['C'], ps['B'])
        elif text_pos == 'T':
            position = (ps['C'], ps['T'])
        elif text_pos == 'L':
            position = (ps['L'], ps['C'])
        elif text_pos == 'R':
            position = (ps['R'], ps['C'])
        else:
            raise NotImplementedError
    elif len(text_pos) == 2:
        a, b = text_pos
        if a in ['T', 'B'] or b in ['L', 'R']:
            position = (ps[b], ps[a])
        else:
            position = (ps[a], ps[b])
    else:
        raise NotImplementedError
    return position