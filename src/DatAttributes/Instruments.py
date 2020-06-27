"""All instrument information in here. I.e. SRS settings, Magnet settings etc"""
import src.DatAttributes.DatAttribute as DA


class NewInstruments(DA.DatAttribute):
    version = '1.0'
    group_name = 'Instruments'

    def _set_default_group_attrs(self):
        pass

    def get_from_HDF(self):
        pass

    def update_HDF(self):
        pass

    def __init__(self, hdf):
        super().__init__(hdf)
        # TODO: finish this

#
# class Instruments(object):
#     """Dat attribute which contains all instrument settings as attributes of itself. Each instrument should be a
#     namedtuple of it's info"""
#     version = '1.0'
#     """
#     Version updates:
#
#     """
#
#     def __init__(self, infodict: Dict):
#         self.version = Instruments.version
#         self.srs1 = DA.get_instr_vals('srs', 1, infodict)
#         self.srs2 = DA.get_instr_vals('srs', 2, infodict)
#         self.srs3 = DA.get_instr_vals('srs', 3, infodict)
#         self.srs4 = DA.get_instr_vals('srs', 4, infodict)
#
#         self.magx = DA.get_instr_vals('mag', 'x', infodict)
#         self.magy = DA.get_instr_vals('mag', 'y', infodict)
#         self.magz = DA.get_instr_vals('mag', 'z', infodict)
#
#         if self.magy is not None:  # Temporary way to get field_y into DataFrame
#             self.field_y = self.magy.field
#
#     def add_mags(self, mag_dict):  # Just for fixing magnet info after initialization
#         infodict = {'Logs': mag_dict}
#         self.magx = DA.get_instr_vals('mag', 'x', infodict)
#         self.magy = DA.get_instr_vals('mag', 'y', infodict)
#         self.magz = DA.get_instr_vals('mag', 'z', infodict)