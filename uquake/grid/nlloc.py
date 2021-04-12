# -*- coding: utf-8 -*-
# ------------------------------------------------------------------
# Filename: <filename>
#  Purpose: <purpose>
#   Author: <author>
#    Email: <email>
#
# Copyright (C) <copyright>
# --------------------------------------------------------------------
"""


:copyright:
    <copyright>
:license:
    GNU Lesser General Public License, Version 3
    (http://www.gnu.org/copyleft/lesser.html)
"""
import numpy as np
from .base import Grid
from pathlib import Path
from uuid import uuid4
import matplotlib.pyplot as plt
from loguru import logger
import skfmm
from multiprocessing import Pool, cpu_count
from functools import partial
from typing import Optional
import h5py
from .base import ray_tracer
from tqdm import tqdm


__cpu_count__ = cpu_count()


valid_phases = ('P', 'S')

valid_grid_types = (
    'VELOCITY',
    'VELOCITY_METERS',
    'SLOWNESS',
    'VEL2',
    'SLOW2',
    'SLOW2_METERS',
    'SLOW_LEN',
    'STACK',
    'TIME',
    'TIME2D',
    'PROB_DENSITY',
    'MISFIT',
    'ANGLE',
    'ANGLE2D'
)

valid_float_types = {
    # NLL_type: numpy_type
    'FLOAT': 'float32',
    'DOUBLE': 'float64'
}

valid_grid_units = (
    'METER',
    'KILOMETER',
)

__velocity_grid_location__ = Path('model')
__time_grid_location__ = Path('time')

__default_grid_units__ = 'METER'
__default_float_type__ = 'FLOAT'


def validate_phase(phase):
    if phase not in valid_phases:
        msg = f'phase should be one of the following valid phases:\n'
        for valid_phase in valid_phases:
            msg += f'{valid_phase}\n'
        raise ValueError(msg)
    return True


def validate_grid_type(grid_type):
    if grid_type.upper() not in valid_grid_types:
        msg = f'grid_type = {grid_type} is not valid\n' \
              f'grid_type should be one of the following valid grid ' \
              f'types:\n'
        for valid_grid_type in valid_grid_types:
            msg += f'{valid_grid_type}\n'
        raise ValueError(msg)
    return True


def validate_grid_units(grid_units):
    if grid_units.upper() not in valid_grid_units:
        msg = f'grid_units = {grid_units} is not valid\n' \
              f'grid_units should be one of the following valid grid ' \
              f'units:\n'
        for valid_grid_unit in valid_grid_units:
            msg += f'{valid_grid_unit}\n'
        raise ValueError(msg)
    return True


def validate_float_type(float_type):
    if float_type.upper() not in valid_float_types.keys():
        msg = f'float_type = {float_type} is not valid\n' \
              f'float_type should be one of the following valid float ' \
              f'types:\n'
        for valid_float_type in valid_float_types:
            msg += f'{valid_float_type}\n'
        raise ValueError(msg)
    return True


def validate(value, choices):
    if value not in choices:
        msg = f'value should be one of the following choices\n:'
        for choice in choices:
            msg += f'{choice}\n'
        raise ValueError(msg)
    return True


def read_grid(base_name, path='.', float_type=__default_float_type__):
    """
    read two parts NLLoc files
    :param base_name:
    :param path: location of grid files
    :param float_type: float type as defined in NLLoc grid documentation
    """
    header_file = Path(path) / f'{base_name}.hdr'
    with open(header_file, 'r') as in_file:
        line = in_file.readline()
        line = line.split()
        shape = tuple([int(line[0]), int(line[1]), int(line[2])])
        origin = np.array([float(line[3]), float(line[4]),
                           float(line[5])]) * 1000
        spacing = np.array([float(line[6]), float(line[7]),
                            float(line[8])]) * 1000

        grid_type = line[9]
        grid_unit = 'METER'

        line = in_file.readline()

        if grid_type in ['ANGLE', 'ANGLE2D', 'TIME', 'TIME2D']:
            line = line.split()
            seed_label = line[0]
            seed = (float(line[1]) * 1000,
                    float(line[2]) * 1000,
                    float(line[3]) * 1000)

        else:
            seed_label = None
            seed = None

    buf_file = Path(path) / f'{base_name}.buf'
    if float_type == 'FLOAT':
        data = np.fromfile(buf_file,
                           dtype=np.float32)
    elif float_type == 'DOUBLE':
        data = np.fromfile(buf_file,
                           dtype=np.float64)
    else:
        msg = f'float_type = {float_type} is not valid\n' \
              f'float_type should be one of the following valid float ' \
              f'types:\n'
        for valid_float_type in valid_float_types:
            msg += f'{valid_float_type}\n'
        raise ValueError(msg)

    data = data.reshape(shape)

    if '.P.' in base_name:
        phase = 'P'
    else:
        phase = 'S'

    # reading the model id file
    mid_file = Path(path) / f'{base_name}.mid'
    if mid_file.exists():
        with open(mid_file, 'r') as mf:
            model_id = mf.readline().strip()

    else:
        model_id = str(uuid4())

        # (self, base_name, data_or_dims, origin, spacing, phase,
        #  seed=None, seed_label=None, value=0,
        #  grid_type='VELOCITY_METERS', grid_units='METER',
        #  float_type="FLOAT", model_id=None):

    network_code = base_name.split('.')[0]
    if grid_type in ['VELOCITY', 'VELOCITY_METERS']:
        return VelocityGrid3D(network_code, data, origin, spacing, phase=phase,
                              model_id=model_id)

    elif grid_type == 'TIME':
        return TTGrid(network_code, data, origin, spacing, seed,
                      seed_label, phase=phase, model_id=model_id)

    elif grid_type == 'ANGLE':
        return AngleGrid(network_code, data, origin, spacing, seed,
                         seed_label, angle_type='AZIMUTH', phase=phase,
                         model_id=model_id)

    else:
        return NLLocGrid(data, origin, spacing, phase,
                         grid_type=grid_type, model_id=model_id,
                         grid_units=grid_unit)


class Seeds:
    __valid_measurement_units__ = ['METERS', 'KILOMETERS']

    def __init__(self, sites=[], units='METERS'):
        """
        specifies a series of source location from an inventory object
        :param sites: a list of sites containing at least the location,
        and site label
        :type sites: list of dictionary

        :Example:

        >>> site = {'label': 'test', 'x': 1000, 'y': 1000, 'z': 1000,
                      'elev': 0.0}
        >>> sites = [site]
        >>> srces = Srces(srces)

        """

        validate(units, self.__valid_measurement_units__)
        self.units = units

        self.sites = sites

    @classmethod
    def from_inventory(cls, inventory):
        """
        create from an inventory object
        :param inventory:
        :type inventory: uquake.core.inventory.Inventory
        """

        srces = []
        for site in inventory.sites:
            srce = {'label': site.code,
                    'x': site.x,
                    'y': site.y,
                    'z': site.z,
                    'elev': 0}
            srces.append(srce)

        return cls(srces)

    @classmethod
    def from_json(cls, json):
        pass

    def add(self, label, x, y, z, elev=0, units='METERS'):
        """
        Add a single site to the source list
        :param label: site label
        :type label: str
        :param x: x location relative to geographic origin expressed
        in the units of measurements for site/source
        :type x: float
        :param y: y location relative to geographic origin expressed
        in the units of measurements for site/source
        :type y: float
        :param z: z location relative to geographic origin expressed
        in the units of measurements for site/source
        :type z: float
        :param elev: elevation above z grid position (positive UP) in
        kilometers for site (Default = 0)
        :type elev: float
        :param units: units of measurement used to express x, y, and z
        ( 'METERS' or 'KILOMETERS')

        """

        validate(units.upper(), self.__valid_measurement_units__)

        self.sites.append({'label': label, 'x': x, 'y': y, 'z': z,
                             elev:'elev'})

        self.units = units.upper()

    def __repr__(self):
        line = ""

        for site in self.sites:

            # test if site name is shorter than 6 characters

            line += f'GTSRCE {site["label"]} XYZ ' \
                    f'{site["x"] / 1000:>15.6f} ' \
                    f'{site["y"] / 1000:>15.6f} ' \
                    f'{site["z"] / 1000:>15.6f} ' \
                    f'0.00\n'

        return line

    @property
    def locs(self):
        seeds = []
        for site in self.sites:
            seeds.append([site['x'], site['y'], site['z']])
        return np.array(seeds)

    @property
    def labels(self):
        seed_labels = []
        for site in self.sites:
            seed_labels.append(site['label'])

        return np.array(seed_labels)


class NLLocGrid(Grid):
    """
    base 3D rectilinear grid object
    """
    def __init__(self, data_or_dims, origin, spacing, phase,
                 value=0, grid_type='VELOCITY_METERS',
                 grid_units=__default_grid_units__,
                 float_type="FLOAT", model_id=None):
        """
        :param data_or_dims: data or data dimensions. If dimensions are
        provided the a homogeneous gris is created with value=value
        :param origin: origin of the grid
        :type origin: list
        :param spacing: the spacing between grid nodes
        :type spacing: list
        :param phase: the useis phase (value 'P' or 'S')
        :type phase: str
        :param value:
        :type value: float
        :param grid_type:
        :type grid_type: str
        :param grid_units:
        :type grid_units: str
        :param float_type:
        :type float_type: str
        :param model_id:
        :type model_id: str
        """

        super().__init__(data_or_dims, spacing=spacing, origin=origin,
                         value=value, resource_id=model_id)

        if validate_phase(phase):
            self.phase = phase.upper()

        if validate_grid_type(grid_type):
            self.grid_type = grid_type.upper()

        # if grid_type.upper() in ['TIME', 'TIME2D', 'ANGLE', 'ANGLE2D']:
        #     if not seed:
        #         raise ValueError('the seeds value must be set for TIME and '
        #                          'ANGLE grids')
        #     if not seed_label:
        #         raise ValueError('the seed_label must be set for TIME '
        #                          'and ANGLE grids')

        # self.seed = seed
        # self.seed_label = seed_label

        if validate_grid_units(grid_units):
            self.grid_units = grid_units.upper()

        if validate_float_type(float_type):
            self.float_type = float_type.upper()

    def _write_grid_data(self, base_name, path='.'):

        Path(path).mkdir(parents=True, exist_ok=True)

        with open(Path(path) / (base_name + '.buf'), 'wb') \
                as out_file:
            if self.float_type == 'FLOAT':
                out_file.write(self.data.astype(np.float32).tobytes())

            elif self.float_type == 'DOUBLE':
                out_file.write(self.data.astype(np.float64).tobytes())

    def _write_grid_header(self, base_name, path='.', seed_label=None,
                           seed=None, seed_units=None):

        # convert 'METER' to 'KILOMETER'
        if self.grid_units == 'METER':
            origin = self.origin / 1000
            spacing = self.spacing / 1000
        else:
            origin = self.origin
            spacing = self.spacing

        line1 = f'{self.shape[0]:d} {self.shape[1]:d} {self.shape[2]:d}  ' \
                f'{origin[0]:f} {origin[1]:f} {origin[2]:f}  ' \
                f'{spacing[0]:f} {spacing[1]:f} {spacing[2]:f}  ' \
                f'{self.grid_type}\n'

        with open(Path(path) / (base_name + '.hdr'), 'w') as out_file:
            out_file.write(line1)

            if self.grid_type in ['TIME', 'ANGLE']:

                if seed_units is None:
                    logger.warning(f'seed_units are not defined. '
                                   f'Assuming same units as grid ('
                                   f'{self.grid_units}')
                if self.grid_units == 'METER':
                    seed = seed / 1000

                line2 = u"%s %f %f %f\n" % (seed_label,
                                            seed[0], seed[1], seed[2])
                out_file.write(line2)

            out_file.write(u'TRANSFORM  NONE\n')

        return True

    def _write_grid_model_id(self, base_name, path='.'):
        with open(Path(path) / (base_name + '.mid'), 'w') as out_file:
            out_file.write(f'{self.model_id}')
        return True

    def write(self, base_name, path='.'):

        self._write_grid_data(base_name, path=path)
        self._write_grid_header(base_name, path=path)
        self._write_grid_model_id(base_name, path=path)

        return True

    @property
    def model_id(self):
        return self.resource_id

    @property
    def site(self):
        return self.seed_label


class ModelLayer:
    """
    1D model varying in Z
    """

    def __init__(self, z_top, value_top):
        """
        :param z_top: Top of the layer z coordinates
        :param value_top: Value at the top of the layer
        """
        self.z_top = z_top
        self.value_top = value_top

    def __repr__(self):
        return f'top - {self.z_top:5d} | value - {self.value_top:5d}\n'


class LayeredVelocityModel(object):

    def __init__(self, model_id=None, velocity_model_layers=None,
                 phase='P', grid_units='METER',
                 float_type=__default_float_type__):
        """
        Initialize
        :param model_id: model id, if not set the model ID is set using UUID
        :type model_id: str
        :param velocity_model_layers: a list of VelocityModelLayer
        :type velocity_model_layers: list
        :param phase: Phase either 'P' or 'S'
        :type phase: str
        """

        if velocity_model_layers is None:
            self.velocity_model_layers = []

        if validate_phase(phase):
            self.phase = phase.upper()

        if validate_grid_units(grid_units):
            self.grid_units = grid_units.upper()

        if validate_float_type(float_type):
            self.float_type = float_type.upper()

        self.grid_type = 'VELOCITY'

        if model_id is None:
            model_id = str(uuid4())

        self.model_id = model_id

    def __repr__(self):
        output = ''
        for i, layer in enumerate(self.velocity_model_layers):
            output += f'layer {i+1:4d} | {layer}'

        return output

    def add_layer(self, layer):
        """
        Add a layer to the model. The layers must be added in sequence from the
        top to the bottom
        :param layer: a LayeredModel object
        """
        if not (type(layer) is ModelLayer):
            raise TypeError('layer must be a VelocityModelLayer object')

        if self.velocity_model_layers is None:
            self.velocity_model_layers = [layer]
        else:
            self.velocity_model_layers.append(layer)

    def gen_1d_model(self, z_min, z_max, spacing):
        # sort the layers to ensure the layers are properly ordered
        z = []
        v = []
        for layer in self.velocity_model_layers:
            z.append(layer.z_top)
            v.append(layer.value_top)

        if np.max(z) < z_max:
            i_z_max = np.argmax(z)
            v_z_max = v[i_z_max]

            z.append(z_max)
            v.append(v_z_max)

        if np.min(z) > z_min:
            i_z_min = np.argmin(z)
            v_z_min = v[i_z_min]

            z.append(z_min)
            v.append(v_z_min)

        i_sort = np.argsort(z)

        z = np.array(z)
        v = np.array(v)

        z = z[i_sort]
        v = v[i_sort]

        z_interp = np.arange(z_min, z_max, spacing[2])
        v_interp = np.interp(z_interp, z, v)

        return z_interp, v_interp

    def gen_3d_grid(self, network_code, dims, origin, spacing):
        model_grid_3d = VelocityGrid3D.from_layered_model(self,
                                                          network_code,
                                                          dims, origin,
                                                          spacing)
        return model_grid_3d

    def plot(self, z_min, z_max, spacing, *args, **kwargs):
        """
        Plot the 1D velocity model
        :param z_min: lower limit of the model
        :param z_max: upper limit of the model
        :param spacing: plotting resolution in z
        :return: matplotlib axis
        """

        z_interp, v_interp = self.gen_1d_model(z_min, z_max, spacing)

        x_label = None
        if self.phase == 'P':
            x_label = 'P-wave velocity'
        elif self.phase == 'S':
            x_label = 's-wave velocity'

        if self.grid_units == 'METER':
            units = 'm'
        else:
            units = 'km'

        y_label = f'z [{units}]'
        ax = plt.axes()
        ax.plot(v_interp, z_interp, *args, **kwargs)
        plt.xlabel(x_label)
        plt.ylabel(y_label)

        ax.set_aspect(2)

        plt.tight_layout()

        return ax


class VelocityGrid3D(NLLocGrid):

    def __init__(self, network_code, data_or_dims, origin, spacing,
                 phase='P', value=0, float_type=__default_float_type__,
                 model_id=None, **kwargs):

        self.network_code = network_code

        if (type(spacing) is int) | (type(spacing) is float):
            spacing = [spacing, spacing, spacing]

        super().__init__(data_or_dims, origin, spacing, phase,
                         value=value, grid_type='VELOCITY_METERS',
                         grid_units='METER', float_type=float_type,
                         model_id=model_id)

    @staticmethod
    def get_base_name(network_code, phase):
        """
        return the base name given a network code and a phase
        :param network_code: Code of the network
        :type network_code: str
        :param phase: Phase, either P or S
        :type phase: str either 'P' or 'S'
        :return: the base name
        """
        validate_phase(phase)
        return f'{network_code.upper()}.{phase.upper()}.mod'

    @classmethod
    def from_layered_model(cls, layered_model, network_code, dims, origin,
                           spacing, **kwargs):
        """
        Generating a 3D grid model from
        :param network_code:
        :param layered_model:
        :param dims:
        :param origin:
        :param spacing:
        :param kwargs:
        :return:
        """

        z_min = origin[-1]
        z_max = z_min + spacing[-1] * dims[-1]

        z_interp, v_interp = layered_model.gen_1d_model(z_min, z_max,
                                                        spacing)

        data = np.zeros(dims)

        for i, v in enumerate(v_interp):
            data[:, :, i] = v_interp[i]

        return cls(network_code, data, origin, spacing,
                   phase=layered_model.phase,
                   float_type=layered_model.float_type,
                   model_id=layered_model.model_id, **kwargs)

    def to_slow_lens(self):
        data = self.spacing[0] / self.data

        return NLLocGrid(data, self.origin, self.spacing,
                         self.phase, grid_type='SLOW_LEN',
                         grid_units=self.grid_units,
                         float_type=self.float_type,
                         model_id=self.model_id)

    def to_time(self, seed, seed_label, sub_grid_resolution=1,
                *args, **kwargs):
        """
        Eikonal solver based on scikit fast marching solver
        :param seed: numpy array location of the seed or origin of useis wave
         in model coordinates
        (usually location of a station or an event)
        :type seed: numpy array
        :param seed_label: seed label (name of station)
        :type seed_label: basestring
        :param sub_grid_resolution: resolution of the grid around the seed.
        Propagating the wavefront on a denser grid around the seed,
        significantly improves the travel time accuracy.
        :rtype: TTGrid
        """

        if not self.in_grid(seed):
            logger.warning(f'{seed_label} is outside the grid. '
                           f'The travel time grid will not be calculated')
            return

        origin = self.origin
        shape = self.shape
        spacing = self.spacing

        extent = (4 * spacing / sub_grid_resolution) * 1.2 \
                 + sub_grid_resolution

        x_i = np.arange(0, extent[0])
        y_i = np.arange(0, extent[1])
        z_i = np.arange(0, extent[2])

        x_i = x_i - np.mean(x_i) + seed[0]
        y_i = y_i - np.mean(y_i) + seed[1]
        z_i = z_i - np.mean(z_i) + seed[2]

        X_i, Y_i, Z_i = np.meshgrid(x_i, y_i, z_i, indexing='ij')

        coords = np.array([X_i.ravel(), Y_i.ravel(), Z_i.ravel()]).T

        vel = self.interpolate(coords, grid_coordinate=False).reshape(
            X_i.shape)

        phi = np.ones_like(X_i)
        phi[int(np.floor(len(x_i) / 2)), int(np.floor(len(y_i) / 2)),
            int(np.floor(len(z_i) / 2))] = 0

        tt_tmp = skfmm.travel_time(phi, vel, dx=sub_grid_resolution)

        tt_tmp_grid = TTGrid(self.network_code, tt_tmp, [x_i[0], y_i[0],
                                                         z_i[0]],
                             [sub_grid_resolution] * 3, seed, seed_label,
                             phase=self.phase, float_type=self.float_type,
                             model_id=self.model_id,
                             grid_units=self.grid_units)

        data = self.data

        xe = origin[0] + np.arange(0, shape[0], 1) * spacing[0]
        ye = origin[1] + np.arange(0, shape[1], 1) * spacing[1]
        ze = origin[2] + np.arange(0, shape[2], 1) * spacing[2]

        Xe, Ye, Ze = np.meshgrid(xe, ye, ze, indexing='ij')

        coords = np.array([Xe.ravel(), Ye.ravel(), Ze.ravel()])

        corner1 = np.array([np.min(x_i), np.min(y_i), np.min(z_i)])
        corner2 = np.array([np.max(x_i), np.max(y_i), np.max(z_i)])

        test = ((coords[0, :] >= corner1[0]) & (coords[0, :] <= corner2[0]) &
                (coords[1, :] >= corner1[1]) & (coords[1, :] <= corner2[1]) &
                (coords[2, :] >= corner1[2]) & (coords[2, :] <= corner2[2]))

        Xe_grid = Xe.ravel()[test]
        Ye_grid = Ye.ravel()[test]
        Ze_grid = Ze.ravel()[test]

        X = np.array([Xe_grid, Ye_grid, Ze_grid]).T

        tt_interp = tt_tmp_grid.interpolate(X, grid_coordinate=False, order=3)

        bias = np.max(tt_interp)

        phi_out = np.ones_like(Xe).ravel()
        phi_out[test] = tt_interp - bias

        phi_out = phi_out.reshape(Xe.shape)

        tt_out = skfmm.travel_time(phi_out, data, dx=spacing)

        # tt_out = tt_out.ravel() + bias
        tt_out = tt_out.ravel() + bias
        tt_out[test] = tt_interp
        tt_out = tt_out.reshape(Xe.shape)

        tt_out_grid = TTGrid(self.network_code, tt_out, self.origin,
                             self.spacing, seed, seed_label, phase=self.phase,
                             float_type=self.float_type,
                             model_id=self.model_id,
                             grid_units=self.grid_units)

        tt_out_grid.data -= tt_out_grid.interpolate(seed.T,
                                                    grid_coordinate=False,
                                                    order=3)

        return tt_out_grid

    def to_time_multi_threaded(self, seeds, seed_labels, cpu_utilisation=0.9,
                               *args, **kwargs):
        """
        Multithreaded version of the Eikonal solver
        based on scikit fast marching solver
        :param seeds: array of seed
        :type seeds: np.array
        :param seed_labels: array of seed_labels
        :type seed_labels: np.array
        :param cpu_utilisation: fraction of the cpu core to be used for the
        processing task (between 0 and 1)
        :type cpu_utilisation: float between 0 and 1
        :param args: arguments to be passed directly to skfmm.travel_time
        function
        :param kwargs: keyword arguments to be passed directly to
        skfmm.travel_time function
        :return: a travel time grid ensemble
        :rtype: TravelTimeEnsemble
        """

        num_threads = int(np.ceil(cpu_utilisation * __cpu_count__))
        # ensuring that the number of threads is comprised between 1 and
        # __cpu_count__
        num_threads = np.max([np.min([num_threads, __cpu_count__]), 1])

        data = []
        for seed, seed_label in zip(seeds, seed_labels):
            if not self.in_grid(seed):
                logger.warning(f'{seed_label} is outside the grid. '
                               f'The travel time grid will not be calculated')
                continue
            data.append((seed, seed_label))

        with Pool(num_threads) as pool:
            results = pool.starmap(self.to_time, data)

        tt_grid_ensemble = TravelTimeEnsemble(results)

        return tt_grid_ensemble

    def write(self, path='.'):

        base_name = self.base_name
        super().write(base_name, path=path)

    @property
    def base_name(self):
        return self.get_base_name(self.network_code, self.phase)


class VelocityGridEnsemble:
    def __init__(self, p_velocity_grid, s_velocity_grid):
        """

        :param p_velocity_grid: p-wave 3D velocity grid
        :type p_velocity_grid: VelocityGrid3D
        :param s_velocity_grid: s-wave 3D velocity grid
        :type s_velocity_grid: VelocityGrid3D
        """

        self.p_velocity_grid = p_velocity_grid
        self.s_velocity_grid = s_velocity_grid
        self.__i__ = 0

    def __getitem__(self, item):
        if item.upper() == 'P':
            return self.p_velocity_grid

        elif item.upper() == 'S':
            return self.s_velocity_grid

        else:
            raise ValueError(f'{item} is not a valid key. '
                             f'The key value must either be "P" or "S"')

    def __iter__(self):
        self.__i__ = 0
        return self

    def __next__(self):
        if self.__i__ < 2:
            if self.__i__ == '0':
                return self.p_velocity_grid
            elif self.__i__ == '1':
                return self.s_velocity_grid
        else:
            raise StopIteration

    # @property
    # def keys(self):
    #     return ['P', 'S']

    def keys(self):
        return ['P', 'S']

    def write(self, path='.'):
        for key in self.keys():
            self[key].write(path=path)

    def to_time_multi_threaded(self, seeds, seed_labels, cpu_utilisation=0.9,
                               *args, **kwargs):

        tt_grid_ensemble = TravelTimeEnsemble([])

        for key in self.keys():
            tt_grids = self[key].to_time_multi_threaded(seeds, seed_labels,
                                                        cpu_utilisation=
                                                        cpu_utilisation,
                                                        *args, **kwargs)

            tt_grid_ensemble += tt_grids

        return tt_grid_ensemble


class SeededGrid(NLLocGrid):
    """
    container for seeded grids (e.g., travel time, azimuth and take off angle)
    """
    __valid_grid_type__ = ['TIME', 'TIME2D', 'ANGLE', 'ANGLE2D']

    def __init__(self, network_code, data_or_dims, origin, spacing, seed,
                 seed_label, phase='P', value=0,
                 grid_units=__default_grid_units__,
                 grid_type='TIME', float_type="FLOAT", model_id=None):
        self.seed = seed
        self.seed_label = seed_label
        self.network_code = network_code

        if grid_type not in self.__valid_grid_type__:
            raise ValueError()
        self.grid_type = grid_type

        super().__init__(data_or_dims, origin, spacing,
                         phase=phase, value=value,
                         grid_type='TIME', grid_units=grid_units,
                         float_type=float_type, model_id=model_id)

    def __repr__(self):
        line = f'Travel Time Grid\n' \
               f'    origin        : {self.origin}\n' \
               f'    spacing       : {self.spacing}\n'  \
               f'    dimensions    : {self.shape}\n' \
               f'    seed label    : {self.seed_label}\n' \
               f'    seed location : {self.seed}'
        return line

    @classmethod
    def get_base_name(cls, network_code, phase, seed_label, grid_type):
        validate_phase(phase)
        if grid_type not in cls.__valid_grid_type__:
            raise ValueError(f'{grid_type} is not a valid grid type')

        base_name = f'{network_code}.{phase}.{seed_label}.' \
                    f'{grid_type.lower()}'
        return base_name

    @property
    def base_name(self):
        base_name = self.get_base_name(self.network_code, self.phase,
                                       self.seed_label, self.grid_type)
        return base_name

    def write(self, path='.'):
        base_name = self.base_name
        self._write_grid_data(base_name, path=path)
        self._write_grid_header(base_name, path=path, seed=self.seed,
                                seed_label=self.seed_label,
                                seed_units=self.grid_units)
        self._write_grid_model_id(base_name, path=path)


class TTGrid(SeededGrid):
    def __init__(self, network_code, data_or_dims, origin, spacing, seed,
                 seed_label, phase='P', value=0, float_type="FLOAT",
                 model_id=None, grid_units=__default_grid_units__):

        super().__init__(network_code, data_or_dims, origin, spacing, seed,
                         seed_label, phase=phase, value=value,
                         grid_type='TIME', float_type=float_type,
                         model_id=model_id, grid_units=grid_units)

    def to_azimuth(self):
        """
        This function calculate the take off angle and azimuth for every
        grid point given a travel time grid calculated using an Eikonal solver
        :return: azimuth and takeoff angles grids
        .. Note: The convention for the takeoff angle is that 0 degree is down.
        """

        gds_tmp = np.gradient(self.data)
        gds = [-gd for gd in gds_tmp]

        azimuth = np.arctan2(gds[0], gds[1]) * 180 / np.pi
        # azimuth is zero northwards

        return AngleGrid(self.network_code, azimuth, self.origin, self.spacing,
                         self.seed, self.seed_label, 'AZIMUTH',
                         phase=self.phase, float_type=self.float_type,
                         model_id=self.model_id, grid_units=self.grid_units)

    def to_takeoff(self):
        gds_tmp = np.gradient(self.data)
        gds = [-gd for gd in gds_tmp]

        hor = np.sqrt(gds[0] ** 2 + gds[1] ** 2)
        takeoff = np.arctan2(hor, -gds[2]) * 180 / np.pi
        # takeoff is zero pointing down
        return AngleGrid(self.network_code, takeoff, self.origin, self.spacing,
                         self.seed, self.seed_label, 'TAKEOFF',
                         phase=self.phase, float_type=self.float_type,
                         model_id=self.model_id, grid_units=self.grid_units)

    def to_azimuth_point(self, coord, grid_coordinate=False, mode='nearest',
                         order=1, **kwargs):
        """
        calculate the azimuth angle at a particular point on the grid for a
        given seed location
        :param coord: coordinates at which to calculate the takeoff angle
        :param grid_coordinate: true if the coordinates are expressed in
        grid space (indices can be fractional) as opposed to model space
        (x, y, z)
        :param mode: interpolation mode
        :param order: interpolation order
        :return: takeoff angle at the location coord
        """

        return self.to_azimuth().interpolate(coord,
                                             grid_coordinate=grid_coordinate,
                                             mode=mode, order=order, **kwargs)

    def to_takeoff_point(self, coord, grid_coordinate=False, mode='nearest',
                         order=1, **kwargs):
        """
        calculate the takeoff angle at a particular point on the grid for a
        given seed location
        :param coord: coordinates at which to calculate the takeoff angle
        :param grid_coordinate: true if the coordinates are expressed in
        grid space (indices can be fractional) as opposed to model space
        (x, y, z)
        :param mode: interpolation mode
        :param order: interpolation order
        :return: takeoff angle at the location coord
        """
        return self.to_takeoff().interpolate(coord,
                                             grid_coordinate=grid_coordinate,
                                             mode=mode, order=order, **kwargs)

    def ray_tracer(self, start, grid_coordinate=False, max_iter=1000,
                   arrival_id=None):
        """
        This function calculates the ray between a starting point (start) and an
        end point, which should be the seed of the travel_time grid, using the
        gradient descent method.
        :param start: the starting point (usually event location)
        :type start: tuple, list or numpy.array
        :param grid_coordinate: true if the coordinates are expressed in
        grid space (indices can be fractional) as opposed to model space
        (x, y, z)
        :param max_iter: maximum number of iteration
        :param arrival_id: id of the arrival associated to the ray if
        applicable
        :rtype: numpy.array
        """

        return ray_tracer(self, start, grid_coordinate=grid_coordinate,
                          max_iter=max_iter, arrival_id=arrival_id,
                          earth_model_id=self.model_id)

    @classmethod
    def from_velocity(cls, seed, seed_label, velocity_grid):
        return velocity_grid.eikonal(seed, seed_label)

    def write(self, path='.'):
        return super().write(path=path)


class TravelTimeEnsemble:
    def __init__(self, travel_time_grids):
        """
        Combine a list of travel time grids together providing meta
        functionality (multi-threaded ray tracing, sorting, travel-time
        calculation for a specific location etc.). It is assumed that
        all grids are compatible, i.e., that all the grids have the same
        origin, spacing and dimensions.
        :param travel_time_grids: a list of TTGrid objects
        """

        self.travel_time_grids = travel_time_grids
        self.__i__ = 0

        for tt_grid in self.travel_time_grids:
            try:
                assert tt_grid.check_compatibility(travel_time_grids[0])
            except:
                raise AssertionError('grids are not all compatible')

    def __len__(self):
        return len(self.travel_time_grids)

    def __add__(self, other):
        for travel_time_grid in other.travel_time_grids:
            self.travel_time_grids.append(travel_time_grid)

        return TravelTimeEnsemble(self.travel_time_grids)

    def __iter__(self):
        self.__i__ = 0
        return self

    def __next__(self):
        if self.__i__ < len(self):
            result = self.travel_time_grids[self.__i__]
            self.__i__ += 1
            return result
        else:
            raise StopIteration

    def __getitem__(self, item):
        if isinstance(item, int):
            return self.travel_time_grids[item]
        if isinstance(item, str):
            tt_grid_out = None
            for travel_time_grid in self.travel_time_grids:
                if travel_time_grid.seed_label == item:
                    return travel_time_grid

            raise KeyError(f'{item} not found')

    def __repr__(self):
        line = f'Number of travel time grids: {len(self)}'
        return line

    @classmethod
    def from_files(cls, path):
        """
        create a travel time ensemble from files located in a directory
        :param path: the base path to the directory containing the travel time
        files.
        :return:
        """
        tt_grids = []
        for fle in Path(path).glob('*time*.hdr'):
            path = fle.parent
            base_name = '.'.join(fle.name.split('.')[:-1])
            tt_grid = read_grid(str(base_name), path=str(path),
                                float_type=__default_float_type__)
            tt_grids.append(tt_grid)

        return cls(tt_grids)

    def select(self, seed_labels: Optional[list] = None,
               phase: Optional[list] = None):
        """
        return the a list of grid corresponding to seed_labels.
        :param seed_labels: seed labels of the travel time grids to return
        :param phase: the phase {'P' or 'S'}, both if None.
        :return: a list of travel time grids
        :rtype: TravelTimeEnsemble
        """

        if (seed_labels is None) and (phase is None):
            return self

        tmp = []
        if seed_labels is None:
            seed_labels = np.unique(self.seed_labels)

        if phase is None:
            phase = ['P', 'S']

        returned_grids = []
        for travel_time_grid in self.travel_time_grids:
            if travel_time_grid.seed_label in seed_labels:
                if travel_time_grid.phase in phase:
                    returned_grids.append(travel_time_grid)

        return TravelTimeEnsemble(returned_grids)

    def sort(self, ascending=True):
        """
        sorting the travel time grid by seed_label
        :param ascending: if true the grids are sorted in ascending order
        :param ascending: bool
        :return: sorted travel time grids.
        :rtype: TravelTimeEnsemble
        """

        i = np.sort(self.seed_labels)

        if not ascending:
            i = i[-1::-1]

        sorted_tt_grids = np.array(self.travel_time_grids)[i]

        return TravelTimeEnsemble(sorted_tt_grids)

    def travel_time(self, seed, grid_coordinate=False,
                    seed_labels=None, sort=True, ascending=True):
        """
        calculate the travel time at a specific point for a series of site
        ids
        :param seed: travel time seed
        :param grid_coordinate: true if the coordinates are expressed in
        grid space (indices can be fractional) as opposed to model space
        (x, y, z)
        :param seed_labels: a list of sites from which to calculate the
        travel time.
        :param sort: sort list if true
        :type sort: bool
        :param ascending: sort in ascending order if true
        :type ascending: bool
        :return: a list of dictionary containing the travel time and site id
        """

        if not self.travel_time_grids[0].in_grid(seed):
            raise ValueError('seed is outside the grid')

        if grid_coordinate:
            seed = self.travel_time_grids[0].transform_from(seed)

        tt_grids = self.select(seed_labels=seed_labels)

        tts = []
        labels = []
        for tt_grid in tt_grids:
            labels.append(tt_grid.seed_label)
            tts.append(tt_grid.interpolate(seed.T, grid_coordinate=False))

        if sort:
            indices = np.argsort(tts, ascending=ascending)
            tts = np.array(tts)[indices]
            labels = np.array(labels)[indices]

        tt_dicts = {'travel_times': tts,
                    'labels': labels}

        return tt_dicts

    def ray_tracer(self, start, seed_labels=None, multithreading=False,
                   cpu_utilisation=0.9, grid_coordinate=False, max_iter=1000):
        """

        :param start: origin of the ray, usually the location of an event
        :param seed_labels: a list of seed labels
        :param grid_coordinate: true if the coordinates are expressed in
        grid space (indices can be fractional) as opposed to model space
        (x, y, z)
        :param multithreading: if True use multithreading
        :param max_iter: maximum number of iteration
        :param cpu_utilisation: fraction of core to use, between 0 and 1.
        The number of core to be use is bound between 1 and the total number of
        cores
        :return: a list of ray
        :rtype: list
        """

        travel_time_grids = self.select(seed_labels=seed_labels)

        if multithreading:

            kwargs = {'grid_coordinate': grid_coordinate,
                      'max_iter': max_iter}

            ray_tracer_func = partial(ray_tracer, **kwargs)

            num_threads = int(np.ceil(cpu_utilisation * __cpu_count__))
            # ensuring that the number of threads is comprised between 1 and
            # __cpu_count__
            num_threads = np.max([np.min([num_threads, __cpu_count__]), 1])

            data = []
            for travel_time_grid in travel_time_grids:
                data.append((travel_time_grid, start))

            with Pool(num_threads) as pool:
                results = pool.starmap(ray_tracer_func, data)

        else:
            results = []
            for travel_time_grid in travel_time_grids:
                results.append(ray_tracer(travel_time_grid, start,
                                          grid_coordinate=grid_coordinate,
                                          max_iter=max_iter))

        return results

    @property
    def seeds(self):
        seeds = []
        for grid in self.travel_time_grids:
            seeds.append(grid.seed)

        return np.array(seeds)

    @property
    def seed_labels(self):
        seed_labels = []
        for grid in self.travel_time_grids:
            seed_labels.append(grid.seed_label)

        return np.array(seed_labels)

    @property
    def shape(self):
        return self.travel_time_grids[0].shape

    @property
    def origin(self):
        return self.travel_time_grids[0].origin

    @property
    def spacing(self):
        return self.travel_time_grids[0].spacing

    def write(self, path='.'):
        for travel_time_grid in self.travel_time_grids:
            travel_time_grid.write(path=path)

    def write_hdf5(self, file_name):
        hf = h5py.File(file_name, 'w')

        shape = self.shape
        origin = self.origin
        spacing = self.spacing
        ngrid = np.product(shape)
        gridlocs = gdef_to_points(shape, origin, spacing)
        hf.create_dataset('grid_locs', data=gridlocs.astype(np.float32))

        hf.attrs['shape'] = shape
        hf.attrs['origin'] = origin
        hf.attrs['spacing'] = spacing
        for phase in ['P', 'S']:
            sorted_tt_grids = self.travel_time_grids.select(phase=phase).sort()
            seeds = sorted_tt_grids.seeds
            seed_labels = np.array(sorted_tt_grids.seed_labels)
            nsta = len(sorted_tt_grids)
            tts = np.zeros((nsta, ngrid), dtype=np.float32)

            for i, tt_grid in enumerate(sorted_tt_grids):
                tts[i] = tt_grid.data.reshape(ngrid)

            seeds = np.array(seeds).astype(np.float32)

            hf.create_dataset(f'tt{phase.lower()}',
                              data=tts)

        hf.create_dataset('locations', data=seeds)
        gdef = np.concatenate((shape, origin, [spacing])).astype(np.int32)
        hf.create_dataset('grid_def', data=gdef)
        hf.create_dataset('stations', data=seed_labels.astype('S4'))
        hf.close()


class AngleGrid(SeededGrid):
    def __init__(self, network_code, data_or_dims, origin, spacing, seed,
                 seed_label, angle_type, phase='P', value=0,
                 float_type="FLOAT", model_id=None,
                 grid_units=__default_grid_units__):

        self.angle_type = angle_type
        super().__init__(network_code, data_or_dims, origin, spacing, seed,
                         seed_label, phase=phase, value=value,
                         grid_type='ANGLE', float_type=float_type,
                         model_id=model_id)

    def write(self, path='.'):
        pass


def gdef_to_points(shape, origin, spacing):
    maxes = origin + shape * spacing
    x = np.arange(origin[0], maxes[0], spacing).astype(np.float32)
    y = np.arange(origin[1], maxes[1], spacing).astype(np.float32)
    z = np.arange(origin[2], maxes[2], spacing).astype(np.float32)
    points = np.zeros((np.product(shape), 3), dtype=np.float32)
    ix = 0

    for xv in x:
        for yv in y:
            for zv in z:
                points[ix] = [xv, yv, zv]
                ix += 1

    return points
