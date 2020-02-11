"""Core of PyDatAnalysis. This should remain unchanged between experiments in general, or be backwards compatible"""

import json
import os
import pickle
import re
import pandas as pd
import src.Configs.Main_Config as cfg
from src.DatCode.Dat import Dat
from src.DFcode.DatDF import DatDF, _dat_exists_in_df
import src.DFcode.DFutil as DU
import src.CoreUtil as CU


################# Sweeplog fixes ##############################


def metadata_to_JSON(data: str) -> dict:
    jsonsubs = cfg.jsonsubs  # Get experiment specific json subs from config
    if jsonsubs is not None:
        for pattern_repl in jsonsubs:
            data = re.sub(pattern_repl[0], pattern_repl[1], data)
    jsondata = json.loads(data)
    return jsondata


def datfactory(datnum, datname, dfname, dfoption, infodict=None):
    datdf = DatDF(dfname=dfname)  # Load DF
    datcreator = _creator(dfoption)  # get creator of Dat instance based on df option
    datinst = datcreator(datnum, datname, datdf, infodict)  # get an instance of dat using the creator
    return datinst  # Return that to caller


def _creator(dfoption):
    if dfoption in ['load', 'load_pickle']:
        return _load_pickle
    if dfoption in ['load_df']:
        return _load_df
    elif dfoption == 'sync':
        return _sync
    elif dfoption == 'overwrite':
        return _overwrite
    else:
        raise ValueError("dfoption must be one of: load, sync, overwrite, load_df")


def _load_pickle(datnum: int, datname, datdf, infodict=None):
    exists = _dat_exists_in_df(datnum, datname, datdf)
    if exists is True:
        datpicklepath = datdf.get_path(datnum, datname=datname)

        if os.path.isfile(datpicklepath) is False:
            inp = input(
                f'Pickle for dat{datnum}[{datname}] doesn\'t exist in "{datpicklepath}", would you like to load using DF[{datdf.name}]?')
            if inp in ['y', 'yes']:
                return _load_df(datnum, datname, datdf, infodict)
            else:
                raise FileNotFoundError(f'Pickle file for dat{datnum}[{datname}] doesn\'t exist')
        with open(datpicklepath, 'rb') as f:  # TODO: Check file exists
            inst = pickle.load(f)
        return inst
    else:
        return None


def _load_df(datnum: int, datname: str, datdf, *args):
    # TODO: make infodict from datDF then run overwrite with same info to recreate Datpickle
    _dat_exists_in_df(datnum, datname, datdf)
    infodict = datdf.infodict(datnum, datname)
    inst = _overwrite(datnum, datname, datdf, infodict)
    return inst


def _sync(datnum, datname, datdf, infodict):
    if (datnum, datname) in datdf.df.index:
        ans = CU.option_input(f'Dat{datnum}[{datname}] already exists, do you want to \'load\' or \'overwrite\'', {'load': 'load', 'overwrite': 'overwrite'})
        if ans == 'load':
            if pd.isna(DU.get_single_value_pd(datdf.df, (datnum, datname), ('picklepath',))) is not True:
                inst = _load_pickle(datnum, datname, datdf)
            else:
                raise NotImplementedError('Not implemented loading from DF yet, infodict from DF needs work first')
                inst = _load_df(datnum, datname,
                                datdf)  # FIXME: Need a better way to get infodict from datDF for this to work
        elif ans == 'overwrite':
            inst = _overwrite(datnum, datname, datdf, infodict)
        else:
            raise ValueError('Must choose either \'load\' or \'overwrite\'')
    else:
        inst = _overwrite(datnum, datname, datdf, infodict)
    return inst


def _overwrite(datnum, datname, datdf, infodict):
    inst = Dat(datnum, datname, infodict, dfname=datdf.name)
    return inst
