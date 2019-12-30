import src.config as cfg
import functools
import inspect
import os


class Dirs:
    """For changing directories for testing purposes"""
    ddir = cfg.ddir  # Save values already in config so they can be restored
    pickledata = cfg.pickledata
    plotdir = cfg.plotdir
    dfdir = cfg.dfdir

    def __init__(self):
        pass

    @staticmethod
    def set_test_dirs():  # So tests can always point to same Dat files
        abspath = os.path.abspath('../fixtures')
        cfg.ddir = os.path.join(abspath, 'dats')
        cfg.pickledata = os.path.join(abspath, 'pickles')
        cfg.plotdir = os.path.join(abspath, 'plots')
        cfg.dfdir = os.path.join(abspath, 'DataFrames')

    @staticmethod
    def reset_dirs():
        print(f'Setting cfg.dir to {Dirs.ddir}')
        cfg.ddir = Dirs.ddir
        cfg.pickledata = Dirs.pickledata
        cfg.plotdir = Dirs.plotdir
        cfg.dfdir = Dirs.dfdir


def change_to_test_dir(func):
    """Temporarily changes all directories to test directories"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        Dirs.set_test_dirs()
        value = func(*args, **kwargs)
        Dirs.reset_dirs()
        return value
    return wrapper


def stackinspecter():
    stack = inspect.stack()
    for i, frame in enumerate(stack):
        for j, val in enumerate(frame):
            print(f'[{i}][{j}] = {val},', end='\t')
        print('')