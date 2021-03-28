from __future__ import annotations
from typing import List, Tuple, Dict, Optional, Any, Callable, Union
import abc
from dataclasses import dataclass
from functools import partial
import logging

from dash_dashboard.base_classes import BasePageLayout, BaseMain, BaseSideBar, PageInteractiveComponents, \
    CommonInputCallbacks, PendingCallbacks
from dash_dashboard.util import triggered_by
from new_dash.base_class_overrides import DatDashPageLayout, DatDashMain, DatDashSidebar
import dash_dashboard.component_defaults as c
from dash_extensions.enrich import ServersideOutput

import dash_html_components as html
import dash_bootstrap_components as dbc
from dash_extensions.enrich import MultiplexerTransform  # Dash Extensions has some super useful things!
from dash import no_update
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from src.DatObject.Make_Dat import get_dat, get_dats, DatHDF
from src.Dash.DatPlotting import OneD, TwoD
import src.UsefulFunctions as U
from src.DatObject.Attributes.DatAttribute import FitInfo

from Analysis.Feb2021.entropy_gamma_final import GammaAnalysisParams
from src.DatObject.Attributes.SquareEntropy import Output, centers_from_fits
from Analysis.Feb2021.common import _get_transition_fit_func_params, square_wave_time_array, _get_data_in_range

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NAME = 'Single Entropy'
URL_ID = 'SingleEntropy'
page_collection = None  # Gets set when running in multipage mode


class Components(PageInteractiveComponents):
    def __init__(self, pending_callbacks: Optional[PendingCallbacks] = None):
        super().__init__(pending_callbacks)
        self.inp_datnum = c.input_box(id_name='inp-datnum', val_type='number', debounce=True,
                                      placeholder='Enter Datnum', persistence=True)

        # Options for viewing saved info
        self.dd_se_name = c.dropdown(id_name='dd-se-names', multi=False)
        self.dd_e_fit_names = c.dropdown(id_name='dd-e-fit-names', multi=True)
        self.dd_t_fit_names = c.dropdown(id_name='dd-t-fit-names', multi=True)
        self.dd_int_info_names = c.dropdown(id_name='dd-int-info-names', multi=True)

        # ##############################
        # Options when calculating fits
        self.tog_calculate = c.toggle(id_name='tog-calculate', persistence=True)
        self.collapse_calculate_options = c.collapse(id_name='collapse-calculate-options')
        self.but_run = c.button(id_name='but-run', text='Run Fits', color='success')

        # Entropy fitting params
        self.inp_setpoint_start = c.input_box(id_name='inp-setpoint-start', val_type='number', persistence=True)
        self.dd_ent_transition_func = c.dropdown(id_name='dd-ent-transition-func', persistence=True)
        self.inp_entropy_fit_width = c.input_box(id_name='inp-entropy-fit-width', persistence=True)
        self.slider_entropy_rows = c.range_slider(id_name='sl-entropy-rows', persistence=True)

        # Transition fitting params
        self.tog_use_transition_only = c.toggle(id_name='tog-transition-only', persistence=True)
        self.inp_transition_only_datnum = c.input_box(id_name='inp-tonly-datnum', persistence=False)
        self.dd_tonly_transition_func = c.dropdown(id_name='dd-tonly-transition-func', persistence=True)
        self.inp_transition_fit_width = c.input_box(id_name='inp-transition-fit-width', persistence=True)
        self.slider_transition_rows = c.range_slider(id_name='sl-transition-rows', persistence=False)

        # Both entropy and transition
        self.dd_center_func = c.dropdown(id_name='dd-center-func', persistence=True)
        self.inp_force_theta = c.input_box(id_name='inp-force-theta', persistence=True)
        self.inp_force_gamma = c.input_box(id_name='inp-force-gamma', persistence=True)

        # Integrated params
        self.inp_force_dt = c.input_box(id_name='inp-force-dt', persistence=True)
        self.inp_force_amp = c.input_box(id_name='inp-force-amp', persistence=True)
        self.tog_from_se = c.toggle(id_name='tog-from-se', persistence=True)

        # CSQ mapping
        self.tog_csq_mapped = c.toggle(id_name='tog-csq-mapped', persistence=True)
        self.inp_csq_datnum = c.input_box(id_name='inp-csq-datnum', persistence=False)

        # Stores result of calculation so that all things depending on calculated don't have to recaculate
        self.store_calculated = c.store(id_name='store-calculated', storage_type='memory', serverside=True)
        # ###############################

        # Graphs
        self.graph_1 = c.graph_area(id_name='graph-1', graph_header='dN/dT',
                                    pending_callbacks=self.pending_callbacks)
        self.graph_2 = c.graph_area(id_name='graph-2', graph_header='Transition',
                                    pending_callbacks=self.pending_callbacks)
        self.graph_3 = c.graph_area(id_name='graph-3', graph_header='Integrated',
                                    pending_callbacks=self.pending_callbacks)

        # Info Area
        self.div_info_title = c.div(id_name='div-info-title')
        self.table_1 = c.table(id_name='tab-efit', dataframe=None)
        self.table_2 = c.table(id_name='tab-tfit', dataframe=None)
        self.table_3 = c.table(id_name='tab-int_info', dataframe=None)

        # ###### Further init of components ##########
        for dd in [self.dd_center_func, self.dd_ent_transition_func, self.dd_tonly_transition_func]:
            dd.options = [{'label': n, 'value': n} for n in ['i_sense', 'i_sense_digamma', 'i_sense_digamma_amplin']]

    def saved_fits_inputs(self) -> List[Tuple[str, str]]:
        """
        Using these in a few CommonInputCallbacks

        se_name, efit_names, tfit_names, int_info_names

        Returns:

        """
        return [
            (self.dd_se_name.id, 'value'),
            (self.dd_e_fit_names.id, 'value'),
            (self.dd_t_fit_names.id, 'value'),
            (self.dd_int_info_names.id, 'value'),
        ]

    def se_params_inputs(self) -> List[Tuple[str, str]]:
        """sp_start, se_transition_func, se_fit_width, se_rows"""
        return [
            (self.inp_setpoint_start.id, 'value'),
            (self.dd_ent_transition_func.id, 'value'),
            (self.inp_entropy_fit_width.id, 'value'),
            (self.slider_entropy_rows.id, 'value'),
        ]

    def t_only_params_inputs(self) -> List[Tuple[str, str]]:
        """use_tonly, tonly_datnum, tonly_func, tonly_width, tonly_rows"""
        return [
            (self.tog_use_transition_only.id, 'value'),
            (self.inp_transition_only_datnum.id, 'value'),
            (self.dd_tonly_transition_func.id, 'value'),
            (self.inp_transition_fit_width.id, 'value'),
            (self.slider_transition_rows.id, 'value'),
        ]

    def e_and_t_params_inputs(self):
        """center_func, force_theta, force_gamma"""
        return [
            (self.dd_center_func.id, 'value'),
            (self.inp_force_theta.id, 'value'),
            (self.inp_force_gamma.id, 'value'),
        ]

    def int_params_inputs(self):
        """force_dt, force_amp, int_from_se"""
        return [
            (self.inp_force_dt.id, 'value'),
            (self.inp_force_amp.id, 'value'),
            (self.tog_from_se.id, 'value'),
        ]


# A reminder that this is helpful for making many callbacks which have similar inputs
class CommonCallbackExample(CommonInputCallbacks):
    components = Components()  # Only use this for accessing IDs only... DON'T MODIFY

    def __init__(self, example):
        super().__init__()  # Just here to shut up PyCharm
        self.example_value = example
        pass

    def callback_names_funcs(self):
        """
        Return a dict of {<name>: <callback_func>}
        """
        return {
            "example": self.example_func(),
        }

    def example_func(self):
        """Part of example, can be deleted"""
        return self.example_value

    @classmethod
    def get_inputs(cls) -> List[Tuple[str, str]]:
        return [
        ]

    @classmethod
    def get_states(cls) -> List[Tuple[str, str]]:
        return []


class SingleEntropyLayout(DatDashPageLayout):

    # Defining __init__ only for typing purposes (i.e. to specify page specific Components as type for self.components)
    def __init__(self, components: Components):
        super().__init__(page_components=components)
        self.components = components

    def get_mains(self) -> List[SingleEntropyMain]:
        return [SingleEntropyMain(self.components), ]

    def get_sidebar(self) -> DatDashSidebar:
        return SingleEntropySidebar(self.components)


class SingleEntropyMain(DatDashMain, abc.ABC):
    name = "SingleEntropyMain"

    # Defining __init__ only for typing purposes (i.e. to specify page specific Components as type for self.components)
    def __init__(self, components: Components):
        super().__init__(page_components=components)
        self.components = components

    def layout(self):
        lyt = html.Div([
            dbc.Row([
                dbc.Col([
                    self.components.graph_1,
                    self.components.graph_2,
                    self.components.graph_3,
                ], width=8),
                dbc.Col([
                    self.components.div_info_title,
                    html.H6('Entropy Fit'),
                    self.components.table_1,
                    html.Hr(),
                    html.H6('Transition Fit'),
                    self.components.table_2,
                    html.Hr(),
                    html.H6('Integrated Info'),
                    self.components.table_3,
                    html.Hr(),

                ], width=4)
            ])
        ])
        return lyt

    def set_callbacks(self):
        components = self.components
        # Graph Callbacks
        for graph, cb_func in {components.graph_1: 'entropy_signal',
                               components.graph_2: 'transition_data',
                               components.graph_3: 'integrated_entropy'}.items():
            self.make_callback(outputs=(graph.graph_id, 'figure'),
                               inputs=GraphCallbacks.get_inputs(),
                               func=GraphCallbacks.get_callback_func(cb_func),
                               states=GraphCallbacks.get_states())

        # Table Callbacks
        self.make_callback(outputs=(self.components.div_info_title.id, 'children'),
                           inputs=(self.components.inp_datnum.id, 'value'),
                           func=lambda datnum: html.H5(
                               f'Dat{datnum}: Fit Info') if datnum is not None else 'Invalid Datnum')

        for table, cb_func in {components.table_1: 'entropy_table',
                               components.table_2: 'transition_table',
                               components.table_3: 'integrated_table'}.items():
            self.make_callback(outputs=TableCallbacks.get_outputs(table),
                               inputs=TableCallbacks.get_inputs(),
                               states=TableCallbacks.get_states(),
                               func=TableCallbacks.get_callback_func(cb_func))


class SingleEntropySidebar(DatDashSidebar):
    id_prefix = 'SingleEntropySidebar'

    # Defining __init__ only for typing purposes (i.e. to specify page specific Components as type for self.components)
    def __init__(self, components: Components):
        super().__init__(page_components=components)
        self.components = components

    def layout(self):
        comps = self.components
        self.components.collapse_calculate_options.children = [
            # Options when calculating fits
            comps.store_calculated,  # Storage for calculations
            comps.but_run,
            c.space(height='10px'),

            # Entropy fitting params
            html.H6('Entropy Specific Params'),
            self.input_wrapper('SP start', comps.inp_setpoint_start),
            self.input_wrapper('T func', comps.dd_ent_transition_func),
            self.input_wrapper('Width', comps.inp_entropy_fit_width),
            self.input_wrapper('Rows', comps.slider_entropy_rows, mode='label'),

            # Transition fitting params
            html.Hr(),
            html.H6('Transition Specific Params'),
            self.input_wrapper('Use T specific', comps.tog_use_transition_only),
            self.input_wrapper('Dat', comps.inp_transition_only_datnum),
            self.input_wrapper('T func', comps.dd_tonly_transition_func),
            self.input_wrapper('Width', comps.inp_transition_fit_width),
            self.input_wrapper('Rows', comps.slider_transition_rows, mode='label'),

            # Both entropy and transition
            html.Hr(),
            html.H6('Entropy and Transition Params'),
            self.input_wrapper('Center Func', comps.dd_center_func),
            self.input_wrapper('Force Theta', comps.inp_force_theta),
            self.input_wrapper('Force Gamma', comps.inp_force_gamma),

            # Integrated params
            html.Hr(),
            html.H6('Integrated Params'),
            self.input_wrapper('Force dT', comps.inp_force_dt),
            self.input_wrapper('Force amp', comps.inp_force_amp),
            self.input_wrapper('From SE', comps.tog_from_se),

            # CSQ mapping
            html.Hr(),
            html.H6('CSQ Mapping Params'),
            self.input_wrapper('Use CSQ mapping', comps.tog_csq_mapped),
            self.input_wrapper('Dat', comps.inp_csq_datnum),
        ]

        lyt = html.Div([
            self.components.dd_main,
            self.input_wrapper('Datnum', self.components.inp_datnum),
            self.input_wrapper('SE Output', self.components.dd_se_name),
            self.input_wrapper('E fits', self.components.dd_e_fit_names),
            self.input_wrapper('T fits', self.components.dd_t_fit_names),
            self.input_wrapper('Int sf', self.components.dd_int_info_names),
            html.Hr(),
            self.input_wrapper('Calculate New Fit', comps.tog_calculate),
            c.space(height='10px'),
            self.components.collapse_calculate_options,
        ])
        return lyt

    def set_callbacks(self):
        cmps = self.components

        # Set Options specific to Dat
        for k, v in {cmps.dd_se_name: 'se outputs',
                     cmps.dd_e_fit_names: 'entropy fits',
                     cmps.dd_t_fit_names: 'transition fits',
                     cmps.dd_int_info_names: 'integrated fits'}.items():
            self.make_callback(outputs=[(k.id, 'options'), (k.id, 'value')],
                               inputs=DatOptionsCallbacks.get_inputs(),
                               states=DatOptionsCallbacks.get_states(),
                               func=DatOptionsCallbacks.get_callback_func(v))

        # Collapse Calculate only options
        self.make_callback(outputs=(cmps.collapse_calculate_options.id, 'is_open'),
                           inputs=(cmps.tog_calculate.id, 'value'),
                           func=lambda val: True if val else False)

        # Setup rows sliders
        for slider_id, datnum_id in {cmps.slider_entropy_rows.id: cmps.inp_datnum.id,
                                     cmps.slider_transition_rows.id: cmps.inp_transition_only_datnum.id}.items():
            self.make_callback(outputs=RowRangeSliderSetupCallback.get_outputs(slider_id),
                               inputs=RowRangeSliderSetupCallback.get_inputs(datnum_id),
                               states=RowRangeSliderSetupCallback.get_states(slider_id),
                               func=RowRangeSliderSetupCallback.get_callback_func()
                               )

        for datnum_id, toggle_id, add_val in zip(
                [cmps.inp_transition_only_datnum.id, cmps.inp_csq_datnum.id],
                [cmps.tog_use_transition_only.id, cmps.tog_csq_mapped.id],
                [1, 2]):
            self.make_callback(outputs=(datnum_id, 'value'),
                               inputs=[
                                   (cmps.inp_datnum.id, 'value'),
                                   (toggle_id, 'value'),
                               ],
                               func=partial(get_datnum_guess, add_val=add_val))

        self.make_callback(serverside_outputs=(cmps.store_calculated.id, 'data'),
                           inputs=CalculateCallback.get_inputs(),
                           func=CalculateCallback.get_callback_func(),
                           states=CalculateCallback.get_states())

# Callback functions
def get_datnum_guess(datnum, tog_val, add_val=0):
    """For guessing which datnum is t_only and csq if selected"""
    if not tog_val or datnum is None:
        return None
    else:
        return datnum + add_val


class RowRangeSliderSetupCallback(c.RangeSliderSetupCallback):
    components = Components()

    def __init__(self, datnum: int, current_value):
        dat = get_dat(datnum) if datnum is not None else None

        min_ = 0
        max_ = 1
        step = 1
        marks = {}
        value = (0, 1)
        if dat is not None:
            yshape = dat.Data.get_data('y').shape[0]
            max_ = yshape
            marks = {int(v): str(int(v)) for v in np.linspace(min_, max_, 5)}
            if current_value and all([min_ < v < max_ for v in current_value]):
                value = current_value
            else:
                value = (min_, max_)
        super().__init__(min=min_, max=max_, step=step, marks=marks, value=value)

    @classmethod
    def get_inputs(cls, datnum_id: str):
        return [(datnum_id, 'value')]

    @classmethod
    def get_states(cls, slider_id_name: str):
        """Use current state of slider to decide whether to reset or keep"""
        return [(slider_id_name, 'value')]


class GraphCallbacks(CommonInputCallbacks):
    components = Components()  # Only use this for accessing IDs only... DON'T MODIFY

    # noinspection PyMissingConstructor
    def __init__(self, datnum, se_name, e_fit_names, t_fit_names, int_info_names,  # Plotting existing
                 ):
        self.datnum: int = datnum
        # Plotting existing
        self.se_name: str = se_name  # SE output names
        self.e_fit_names: List[str] = listify_dash_input(e_fit_names)
        self.t_fit_names: List[str] = listify_dash_input(t_fit_names)
        self.int_names: List[str] = listify_dash_input(int_info_names)

        self.run = triggered_by(self.components.but_run.id)  # Don't actually care about n_clicks

        # ################# Post calculations
        self.dat = get_dat(self.datnum) if self.datnum is not None else None

    @classmethod
    def get_inputs(cls) -> List[Tuple[str, str]]:
        cmps = cls.components
        return [
            (cmps.inp_datnum.id, 'value'),
            *cmps.saved_fits_inputs(),
            # (cmps.dd_se_name.id, 'value'),
            # (cmps.dd_e_fit_names.id, 'value'),
            # (cmps.dd_t_fit_names.id, 'value'),
            # (cmps.dd_int_info_names.id, 'value'),
            (cmps.but_run.id, 'n_clicks'),
        ]

    @classmethod
    def get_states(cls) -> List[Tuple[str, str]]:
        cmps = cls.components
        return [
        ]

    def callback_names_funcs(self):
        """
        Return a dict of {<name>: <callback_func>}
        """
        return {
            "entropy_signal": self.entropy_signal(),
            "transition_data": self.transition_data(),
            "integrated_entropy": self.integrated_entropy(),
        }

    def _correct_call_args(self) -> bool:
        """Common check for bad call args which shouldn't be used for plotting"""
        if any([self.dat is None, not is_square_entropy_dat(self.dat)]):
            return False
        return True

    def entropy_signal(self) -> go.Figure:
        """dN/dT figure"""

        def _avg_fig():
            dat = self.dat
            plotter = OneD(dat=dat)
            fig = plotter.figure(title=f'Dat{dat.datnum}: dN/dT')
            out = dat.SquareEntropy.get_Outputs(name=self.se_name, check_exists=True)
            x = out.x
            data = out.average_entropy_signal
            fig.add_trace(plotter.trace(data=data, x=x, mode='lines', name='Data'))
            existing_names = dat.Entropy.fit_names
            for n in self.e_fit_names:
                if n in existing_names:
                    fit = dat.Entropy.get_fit(name=n)
                    fig.add_trace(plotter.trace(data=fit.eval_fit(x=x), x=x, name=f'{n}_fit', mode='lines'))
            return fig

        if not self._correct_call_args():
            logger.warning(f'Bad call args to GraphCallback')
            return go.Figure()

        if self.run is False:
            return _avg_fig()
        else:
            return go.Figure()

    def transition_data(self) -> go.Figure:
        """Transition figure"""
        if not self._correct_call_args():
            logger.warning(f'Bad call args to GraphCallback')
            return go.Figure()
        dat = self.dat
        plotter = OneD(dat=dat)
        fig = plotter.figure(title=f'Dat{dat.datnum}: Transition')
        out = dat.SquareEntropy.get_Outputs(name=self.se_name, check_exists=True)
        x = out.x
        datas = out.averaged
        biases = dat.SquareEntropy.square_awg.AWs[0][0]
        for data, label in zip(datas, ['0nA_0', f'{biases[1] / 10:.1f}nA', '0nA_1', f'{biases[3] / 10:.1f}nA']):
            fig.add_trace(plotter.trace(data=data, x=x, mode='lines', name=label))
        existing_names = dat.SquareEntropy.get_fit_names(which='transition')
        for n in self.t_fit_names:
            if n in existing_names:
                fit = dat.SquareEntropy.get_fit(fit_name=n, which_fit='transition')
                fig.add_trace(plotter.trace(data=fit.eval_fit(x=x), x=x, name=f'{n}_fit', mode='lines'))
        return fig

    def integrated_entropy(self) -> go.Figure:
        """Integrated figure"""
        if not self._correct_call_args():
            logger.warning(f'Bad call args to GraphCallback')
            return go.Figure()
        dat = self.dat
        plotter = OneD(dat=dat)
        fig = plotter.figure(title=f'Dat{dat.datnum}: Integrated')
        out = dat.SquareEntropy.get_Outputs(name=self.se_name, check_exists=True)
        x = out.x
        data = out.average_entropy_signal
        existing_names = dat.Entropy.get_integration_info_names()
        for n in self.int_names:
            if n in existing_names:
                int_data = dat.Entropy.get_integrated_entropy(name=n, data=data)
                fig.add_trace(plotter.trace(data=int_data, x=x, name=f'{n}', mode='lines'))
        return fig


class DatOptionsCallbacks(CommonInputCallbacks):
    """Common callback to fill in options for dats"""
    components = Components()

    # noinspection PyMissingConstructor
    def __init__(self, datnum: int, se_name, e_names, t_names, int_names):
        self.datnum: Optional[int] = datnum
        self.se_name: str = se_name
        self.e_names: List[str] = listify_dash_input(e_names)
        self.t_names: List[str] = listify_dash_input(t_names)
        self.int_names: List[str] = listify_dash_input(int_names)

        # Generated
        self.dat = get_dat(datnum) if self.datnum is not None else None

    @classmethod
    def get_inputs(cls) -> List[Tuple[str, str]]:
        return [
            (cls.components.inp_datnum.id, 'value'),
        ]

    @classmethod
    def get_states(cls) -> List[Tuple[str, str]]:
        cmps = cls.components
        return [
            # Saved fits info
            *cmps.saved_fits_inputs(),
        ]

    def callback_names_funcs(self) -> dict:
        return {
            'se outputs': self.se_outputs(),
            'entropy fits': self.entropy(),
            'transition fits': self.transition(),
            'integrated fits': self.integrated(),
        }

    @staticmethod
    def _val(new_opts: List[str], current: Union[str, List[str]]) -> Union[str, List[str]]:
        if isinstance(current, str):
            current = [current]

        values = []
        if new_opts is not None and current is not None:
            for x in current:
                if x in new_opts:
                    values.append(x)
        if len(values) == 1:
            values = values[0]  # return str for only one value selected to keep in line with how dash does things
        elif len(values) == 0:
            if len(new_opts) > 0:
                values = new_opts[0]
            else:
                values = ''
        return values

    @staticmethod
    def _list_to_options(opts_list: List[str]) -> List[Dict[str, str]]:
        return [{'label': k, 'value': k} for k in opts_list]

    def opts_val_return(self, new_opts, current) -> Tuple[List[Dict[str, str]], str]:
        val = self._val(new_opts, current)
        opts = self._list_to_options(new_opts)
        return opts, val

    @classmethod
    def output_for_id(cls, id_name: str) -> List[Tuple[str, str]]:
        return [(id_name, 'options'), (id_name, 'value')]

    def _valid_call(self) -> bool:
        if any([self.dat is None, not is_square_entropy_dat(self.dat)]):
            return False
        return True

    def se_outputs(self) -> Tuple[List[Dict[str, str]], str]:
        """Options for SE_output dropdown"""
        if not self._valid_call():
            return [], no_update
        return self.opts_val_return(self.dat.SquareEntropy.Output_names(), self.se_name)

    def entropy(self) -> Tuple[List[Dict[str, str]], str]:
        """Options for E fits dropdown"""
        if not self._valid_call():
            return [], no_update
        return self.opts_val_return(self.dat.Entropy.fit_names, self.e_names)

    def transition(self) -> Tuple[List[Dict[str, str]], str]:
        """Options for T fits dropdown"""
        if not self._valid_call():
            return [], no_update
        return self.opts_val_return(self.dat.SquareEntropy.get_fit_names(which='transition'), self.t_names)

    def integrated(self) -> Tuple[List[Dict[str, str]], str]:
        """Options for Int info dropdown"""
        if not self._valid_call():
            return [], no_update
        return self.opts_val_return(self.dat.Entropy.get_integration_info_names(), self.int_names)


class TableCallbacks(CommonInputCallbacks):
    components = Components()  # For ID's only

    def __init__(self, se_name, e_names, t_names, int_names, datnum):
        super().__init__()  # Shutting up PyCharm
        self.se_name: str = se_name
        self.e_names: List[str] = listify_dash_input(e_names)
        self.t_names: List[str] = listify_dash_input(t_names)
        self.int_names: List[str] = listify_dash_input(int_names)
        self.datnum: Optional[int] = datnum

        # Generated
        self.dat = get_dat(datnum) if self.datnum is not None else None

    @staticmethod
    def get_outputs(table: dbc.Table) -> List[Tuple[str, str]]:
        """Columns and Data for Table callbacks"""
        return [(table.id, 'columns'), (table.id, 'data')]

    @classmethod
    def get_inputs(cls) -> List[Tuple[str, str]]:
        return [
            (cls.components.dd_se_name.id, 'value'),
            (cls.components.dd_e_fit_names.id, 'value'),
            (cls.components.dd_t_fit_names.id, 'value'),
            (cls.components.dd_int_info_names.id, 'value'),
        ]

    @classmethod
    def get_states(cls) -> List[Tuple[str, str]]:
        return [
            (cls.components.inp_datnum.id, 'value'),
        ]

    def callback_names_funcs(self):
        return {
            'entropy_table': self.entropy_table(),
            'transition_table': self.transition_table(),
            'integrated_table': self.integration_table(),
        }

    def _valid_call(self) -> bool:
        """Common check for bad call args which shouldn't be used for plotting"""
        if any([self.dat is None, not is_square_entropy_dat(self.dat)]):
            return False
        return True

    @staticmethod
    def _df_to_table_props(df: pd.DataFrame) -> Tuple[List[Dict[str, str]], List[dict]]:
        df.insert(0, 'Name', df.pop('name'))
        df = df.applymap(lambda x: f'{x:.3g}' if isinstance(x, (float, np.float)) else x)
        return [{'name': col, 'id': col} for col in df.columns], df.to_dict('records')

    def _get_fit_table(self, existing_names: List[str], requested_names: List[str], fit_getter: Callable):
        dfs = []
        for name in requested_names:
            if name in existing_names:
                fit = fit_getter(name)
                df = fit.to_df()
                df['name'] = name
                dfs.append(df)
        if len(dfs) == 0:
            return [], []
        df = pd.concat(dfs)
        return self._df_to_table_props(df)

    def entropy_table(self):
        """Table of fit values for Entropy fits"""
        if not self._valid_call():
            return [], []
        return self._get_fit_table(existing_names=self.dat.Entropy.fit_names,
                                   requested_names=self.e_names,
                                   fit_getter=lambda fit_name: self.dat.Entropy.get_fit(name=fit_name))

    def transition_table(self):
        """Table of fit values for Transition fits"""
        if not self._valid_call():
            return [], []
        return self._get_fit_table(existing_names=self.dat.SquareEntropy.get_fit_names(which='transition'),
                                   requested_names=self.t_names,
                                   fit_getter=lambda fit_name: self.dat.SquareEntropy.get_fit(fit_name=fit_name,
                                                                                              which_fit='transition'))

    def integration_table(self):
        """Table of fit values for Integrated Infos"""
        if not self._valid_call():
            return [], []
        return self._get_fit_table(existing_names=self.dat.Entropy.get_integration_info_names(),
                                   requested_names=self.int_names,
                                   fit_getter=lambda fit_name: self.dat.Entropy.get_integration_info(name=fit_name))


class CalculateCallback(CommonInputCallbacks):
    components = Components()

    # noinspection PyMissingConstructor
    def __init__(self, run,
                 datnum,
                 sp_start, se_transition_func, se_fit_width, se_rows,
                 use_tonly, tonly_datnum, tonly_func, tonly_width, tonly_rows,
                 center_func, force_theta, force_gamma,
                 force_dt, force_amp, int_from_se,
                 use_csq, csq_datnum,
                 ):
        self.run = triggered_by(run)  # i.e. True if run was the trigger
        self.datnum = datnum

        # SE fitting
        self.sp_start = sp_start if sp_start else 0.0
        self.ent_transition_func = se_transition_func
        self.ent_width = se_fit_width
        self.ent_rows = se_rows

        # Tonly fitting
        self.use_tonly = use_tonly
        self.tonly_datnum = tonly_datnum
        self.tonly_func = tonly_func
        self.tonly_width = tonly_width
        self.tonly_rows = tonly_rows

        self.center_func = center_func
        self.force_theta = force_theta
        self.force_gamma = force_gamma

        # Integration info
        self.force_dt = force_dt
        self.force_amp = force_amp
        self.int_from_se = int_from_se

        # CSQ mapping
        self.csq_map = use_csq
        self.csq_datnum = csq_datnum

        # ## Post init
        self.dat = get_dat(self.datnum) if self.datnum else None

    @classmethod
    def get_inputs(cls) -> List[Tuple[str, str]]:
        return [
            (cls.components.but_run.id, 'n_clicks')
        ]

    @classmethod
    def get_states(cls) -> List[Tuple[str, str]]:
        return [
            (cls.components.inp_datnum.id, 'value'),
            *cls.components.se_params_inputs(),
            *cls.components.t_only_params_inputs(),
            *cls.components.e_and_t_params_inputs(),
            *cls.components.int_params_inputs(),
            (cls.components.tog_csq_mapped.id, 'value'),
            (cls.components.inp_csq_datnum.id, 'value'),
        ]

    @classmethod
    def get_outputs(cls, id_name: str) -> Tuple[str, str]:
        return id_name, 'data'

    def callback_names_funcs(self):
        return {
            'calculate': self.calculate(),
        }

    @classmethod
    def get_callback_func(cls, *args):
        return super().get_callback_func('calculate')

    def calculate(self) -> StoreData:
        def get_centers(func_name: str, rows):
            row_fits = [self.dat.SquareEntropy.get_fit(which_fit='transition',
                                                       which='row', row=row,
                                                       fit_name=func_name, check_exists=True) for row in range(*rows)]
            return centers_from_fits(row_fits)

        def get_setpoints(start_time, fin_time=None):
            sps = [start_time, fin_time]
            sp_times = square_wave_time_array(self.dat.SquareEntropy.square_awg)
            start, fin = [U.get_data_index(sp_times, sp) for sp in sps]
            return start, fin

        def get_data(rows, csq):
            s, f = rows
            if csq:
                data = self.dat.Data.get_data('csq_mapped')[s:f]
            else:
                data = self.dat.Transition.get_data('i_sense')[s:f]
            return data

        params = GammaAnalysisParams(
            csq_mapped=self.csq_map,
            save_name='NOT SAVED',
            entropy_datnum=self.datnum,
            setpoint_start=self.sp_start,
            entropy_transition_func_name=self.ent_transition_func, entropy_fit_width=self.ent_width,
            entropy_data_rows=self.ent_rows,
            force_dt=self.force_dt, force_amp=self.force_amp,
            sf_from_square_transition=self.int_from_se,
            force_theta=self.force_theta, force_gamma=self.force_gamma,  # Applies to entropy and transition only
            transition_center_func_name=self.center_func,
            # Tonly stuff set below if used
        )

        sp_start, sp_fin = get_setpoints(params.setpoint_start, None)

        x = self.dat.Data.get_data('x')
        data = get_data(params.entropy_data_rows, params.csq_mapped)

        centers = get_centers(params.entropy_transition_func_name, params.entropy_data_rows)

        t_func, t_params = _get_transition_fit_func_params(params.entropy_datnum, x=x, data=np.mean(data, axis=0),
                                                           t_func_name=params.entropy_transition_func_name,
                                                           theta=params.force_theta, gamma=params.force_gamma)
        inputs = self.dat.SquareEntropy.get_Inputs(name=None, x_array=x, i_sense=data, centers=centers,
                                                   save_name=None,  # Do not save
                                                   )
        process_params = self.dat.SquareEntropy.get_ProcessParams(name=None,
                                                                  setpoint_start=sp_start, setpoint_fin=sp_fin,
                                                                  transition_fit_func=t_func,
                                                                  transition_fit_params=t_params,
                                                                  save_name=None,  # Do not save
                                                                  )
        out = self.dat.SquareEntropy.get_Outputs(name=None,
                                                 inputs=inputs, process_params=process_params,
                                                 calculate_only=True)

        # Transition part
        if self.use_tonly:
            params.transition_only_datnum = self.tonly_datnum
            params.transition_func_name = self.tonly_func
            params.transition_fit_width = self.tonly_width
            params.transition_data_rows = self.tonly_rows
            transition_data = self._transition_calculate(params)
        else:
            transition_data = None

        return StoreData(analysis_params=params, SE_output=out, transition_data=transition_data)

    def _transition_calculate(self, params: GammaAnalysisParams) -> TonlyData:
        def get_data(rows, csq, transition_dat) -> Tuple[np.ndarray, np.ndarray]:
            if csq:
                name = 'csq_mapped'
                data_group_name = 'Data'
            else:
                name = 'i_sense'
                data_group_name = 'Transition'
            s, f = rows

            x = transition_dat.Data.get_data('x', data_group_name=data_group_name)
            data = transition_dat.Data.get_data(name, data_group_name=data_group_name)[s:f]
            return x, data

        def get_centers(rows, name, transition_dat) -> np.ndarray:
            s, f = rows
            row_ids = range(s if s else 0, f if f else transition_dat.Data.get_data('y').shape[0])  # all the rows

            center_fits = [transition_dat.Transition.get_fit(which='row', row=row, name=name,
                                                             check_exists=True) for row, d in zip(row_ids, data)]
            cs = np.array([f.best_values.mid for f in center_fits])
            return cs

        def calculate_fit(x_, data_, width, func_name, theta, gamma, transition_dat: DatHDF):
            x_, data_ = _get_data_in_range(x_, data_, width)

            func, t_pars = _get_transition_fit_func_params(transition_dat.datnum, x_, data_, func_name, theta, gamma)

            return transition_dat.Transition.get_fit(fit_func=func, initial_params=t_pars,
                                                     x=x_, data=data_,
                                                     calculate_only=True)

        t_dat = get_dat(params.transition_only_datnum)
        x, data = get_data(params.transition_data_rows, params.csq_mapped, t_dat)

        centers = get_centers(params.transition_data_rows, params.transition_center_func_name, t_dat)

        data_avg, x_avg = U.mean_data(x=x, data=data, centers=centers, method='linear', return_x=True)

        fit = calculate_fit(x_=x_avg, data_=data_avg, width=params.transition_fit_width,
                            func_name=params.transition_func_name,
                            theta=params.force_theta, gamma=params.force_gamma,
                            transition_dat=t_dat)

        transition_calculated = TonlyData(x=x_avg, data=data_avg, fit=fit)
        return transition_calculated


@dataclass
class TonlyData:
    x: np.ndarray
    data: np.ndarray
    fit: FitInfo


@dataclass
class StoreData:
    analysis_params: GammaAnalysisParams
    SE_output: Output
    transition_data: Optional[TonlyData] = None


def listify_dash_input(val: Optional[str, List[str]]) -> List[str]:
    """Makes dash inputs into a list of strings instead of any of (None, '', 'value' or ['value1', 'value2'])"""
    if isinstance(val, list):
        return val
    elif val is None or val == '':
        return []
    elif isinstance(val, str):
        return [val]
    else:
        raise RuntimeError(f"Don't know how to listify {val}")


def is_square_entropy_dat(dat: Union[None, DatHDF]) -> bool:
    if dat is None:
        return False
    try:
        awg = dat.Logs.awg
    except U.NotFoundInHdfError:
        return False
    return True


# Required for multipage
def layout(*args):  # *args only because dash_extensions passes in the page name for some reason
    inst = SingleEntropyLayout(Components())
    inst.page_collection = page_collection
    return inst.layout()


def callbacks(app):
    inst = SingleEntropyLayout(Components(pending_callbacks=PendingCallbacks()))
    inst.page_collection = page_collection
    inst.layout()  # Most callbacks are generated while running layout
    return inst.run_all_callbacks(app)


if __name__ == '__main__':
    from dash_dashboard.app import test_page

    test_page(layout=layout, callbacks=callbacks, single_threaded=False, port=8050)
