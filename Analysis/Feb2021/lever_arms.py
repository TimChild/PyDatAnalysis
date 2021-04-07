"""
Trying to figure out if the lever arm of the ACC gate changes significantly as the coupling of the QD to the reservoir
increases.
Going to use potential in the reservoir as a way to change the chemical potential in the dot in a way which hopefully
is not affected by the coupling strength to the reservoir
"""
from src.DatObject.Make_Dat import get_dat, get_dats, DatHDF
from src.Dash.DatPlotting import OneD, TwoD
import src.UsefulFunctions as U

import numpy as np
import lmfit as lm
import plotly.graph_objects as go
import plotly.io as pio
from typing import Tuple

pio.renderers.default = 'browser'

DATS1 = list(range(5240, 5257 + 1))  # many rows from -1->+1mV in reservoir
DATS2 = list(range(5258, 5263 + 1))  # Two slow rows at -1 and +1mV in res only


def _get_data(dat, measure_freq: float, differentiated=True) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = dat.Data.get_data('i_sense')
    x = dat.Data.get_data('x')
    y = dat.Data.get_data('y')
    data = U.decimate(data, measure_freq=measure_freq, numpnts=400)
    if differentiated:
        data = np.diff(data, axis=-1)
    x = U.get_matching_x(x, data)
    return x, y, data


def plot_2d(dat: DatHDF, differentiated=True) -> go.Figure:
    plotter = TwoD(dat=dat)

    x, y, data = _get_data(dat, dat.Logs.measure_freq, differentiated=differentiated)

    title_prepend = ''
    if differentiated:
        title_prepend = 'Differentiated '

    fig = plotter.plot(x=x, y=y, data=data, title=f'Dat{dat.datnum}: {title_prepend}Res Potential vs ACC<br>'
                                             f'ESC={dat.Logs.fds["ESC"]:.1f}mV')
    return fig


def fit_centers(dat: DatHDF):
    centers = np.array(dat.Transition.get_centers()).astype(np.float32)
    ys = dat.Data.get_data('y').astype(np.float32)
    line = lm.models.LinearModel()
    params = line.guess(centers, x=ys)
    fit = line.fit(centers, x=ys, params=params)
    return fit



if __name__ == '__main__':
    fits = []
    dats = get_dats(DATS2)
    for dat in dats:
        fig = plot_2d(dat, differentiated=True)
        fig.show()
        fits.append(fit_centers(dat))

    # for fit, dat in zip(fits, dats):
    #     print(f'Dat{dat.datnum}:\n'
    #           f'Slope: {fit.best_values["slope"]:.3f}\n'
    #           f'Intercept: {fit.best_values["intercept"]:.2f}\n')
    #
    # slopes = [fit.best_values['slope'] for fit in fits]
    # escs = [dat.Logs.fds['ESC'] for dat in dats]
    #
    # plotter = OneD(dat=None)
    # fig = plotter.plot(data=slopes, x=escs, title=f'Dats{dats[0].datnum}-{dats[-1].datnum}: Slope of transition '
    #                                               f'center vs Res potential for varying ESC (coupling gate)',
    #                    mode='markers+lines',
    #                    xlabel='ESC /mV', ylabel='Slope')
    # fig.show()
