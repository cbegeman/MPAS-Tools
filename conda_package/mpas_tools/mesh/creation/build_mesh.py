"""
This script performs the first step of initializing the global ocean.  This
includes:
Step 1. Build cellWidth array as function of latitude and longitude
Step 2. Build mesh using JIGSAW
Step 3. Convert triangles from jigsaw format to netcdf
Step 4. Convert from triangles to MPAS mesh
Step 5. Create vtk file for visualization
"""

from __future__ import absolute_import, division, print_function, \
    unicode_literals

import xarray
import argparse
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy

from mpas_tools.mesh.conversion import convert
from mpas_tools.io import write_netcdf
from mpas_tools.viz.paraview_extractor import extract_vtk

from mpas_tools.mesh.creation.jigsaw_driver import jigsaw_driver
from mpas_tools.mesh.creation.jigsaw_to_netcdf import jigsaw_to_netcdf
from mpas_tools.mesh.creation.inject_bathymetry import inject_bathymetry
from mpas_tools.mesh.creation.inject_meshDensity import inject_meshDensity
from mpas_tools.mesh.creation.inject_preserve_floodplain import \
    inject_preserve_floodplain
from mpas_tools.viz.colormaps import register_sci_viz_colormaps

import sys
import os
# add the current working directory to the system path
sys.path.append(os.getcwd())
import define_base_mesh
# okay, now we don't want to get anything else from CWD
del sys.path[-1]

def build_mesh(
        preserve_floodplain=False,
        floodplain_elevation=20.0,
        do_inject_bathymetry=False,
        geometry='sphere',
        plot_cellWidth=True):
    """
    Build an MPAS mesh using JIGSAW with the given cell sizes as a function of
    latitude and longitude (on a sphere) or x and y (on a plane).

    The user must define a local python module ``define_base_mesh`` that
    provides a function that returns a 2D array ``cellWidth`` of cell sizes in
    kilometers.

    If ``geometry = 'sphere'``, this function is called ``cellWidthVsLatLon()``
    and also returns 1D ``lon`` and ``lat`` arrays.

    If ``geometry = 'plane'`` (or any value other than `'sphere'``), the
    function is called ``cellWidthVsXY()`` and returns 4 arrays in addition to
    ``cellWidth``: 1D ``x`` and ``y`` arrays defining planar coordinates in
    meters; as well as ``geom_points``, list of point coordinates for bounding
    polygon for the planar mesh; and ``geom_edges``, list of edges between
    points in ``geom_points`` that define the bounding polygon.

    The result is ``base_mesh.nc`` as well as several intermediate files:
    ``mesh.log``, ``mesh-HFUN.msh``, ``mesh.jig``, ``mesh-MESH.msh``,
    ``mesh.msh``, and ``mesh_triangles.nc``.

    The ``extract_vtk()`` function is used to produce a VTK file in the
    ``base_mesh_vtk`` directory that can be viewed in ParaVeiw.

    Parameters
    ----------
    preserve_floodplain : bool, optional
        Whether a flood plain (bathymetry above z = 0) should be preserved in
        the mesh.  If so, a field ``cellSeedMask`` is added to the MPAS mesh
        indicating positive elevations that should be preserved.

    floodplain_elevation : float, optional
        The elevation in meters to which the flood plain is preserved.

    do_inject_bathymetry : bool, optional
        Whether one of the default bathymetry datasets, ``earth_relief_15s.nc``
        or ``topo.msh``, should be added to the MPAS mesh in the field
        ``bottomDepthObserved``.  If so, a local link to one of these file names
        must exist.

    geometry : {'sphere', 'plane'}, optional
        Whether the mesh is spherical or planar

    plot_cellWidth : bool, optional
        If ``geometry = 'sphere'``, whether to produce a plot of ``cellWidth``.
        If so, it will be written to ``cellWidthGlobal.png``.
    """

    if geometry == 'sphere':
        on_sphere = True
    else:
        on_sphere = False

    print('Step 1. Build cellWidth array as function of horizontal coordinates')
    if on_sphere:
        cellWidth, lon, lat = define_base_mesh.cellWidthVsLatLon()
        da = xarray.DataArray(cellWidth,
                              dims=['lat', 'lon'],
                              coords={'lat': lat, 'lon': lon},
                              name='cellWidth')
        cw_filename = 'cellWidthVsLatLon.nc'
        da.to_netcdf(cw_filename)
        plot_cellWidth = True
        if plot_cellWidth:
            register_sci_viz_colormaps()
            fig = plt.figure(figsize=[16.0, 8.0])
            ax = plt.axes(projection=ccrs.PlateCarree())
            ax.set_global()
            im = ax.imshow(cellWidth, origin='lower',
                           transform=ccrs.PlateCarree(),
                           extent=[-180, 180, -90, 90], cmap='3Wbgy5',
                           zorder=0)
            ax.add_feature(cartopy.feature.LAND, edgecolor='black', zorder=1)
            gl = ax.gridlines(
                crs=ccrs.PlateCarree(),
                draw_labels=True,
                linewidth=1,
                color='gray',
                alpha=0.5,
                linestyle='-', zorder=2)
            gl.top_labels = False
            gl.right_labels = False
            plt.title(
                'Grid cell size, km, min: {:.1f} max: {:.1f}'.format(
                cellWidth.min(),cellWidth.max()))
            plt.colorbar(im, shrink=.60)
            fig.canvas.draw()
            plt.tight_layout()
            plt.savefig('cellWidthGlobal.png', bbox_inches='tight')
            plt.close()

    else:
        cellWidth, x, y, geom_points, geom_edges = define_base_mesh.cellWidthVsXY()
        da = xarray.DataArray(cellWidth,
                              dims=['y', 'x'],
                              coords={'y': y, 'x': x},
                              name='cellWidth')
        cw_filename = 'cellWidthVsXY.nc'
        da.to_netcdf(cw_filename)

    print('Step 2. Generate mesh with JIGSAW')
    if on_sphere:
        jigsaw_driver(cellWidth, lon, lat)
    else:
        jigsaw_driver(
            cellWidth,
            x,
            y,
            on_sphere=False,
            geom_points=geom_points,
            geom_edges=geom_edges)

    print('Step 3. Convert triangles from jigsaw format to netcdf')
    jigsaw_to_netcdf(msh_filename='mesh-MESH.msh',
                     output_name='mesh_triangles.nc', on_sphere=on_sphere)

    print('Step 4. Convert from triangles to MPAS mesh')
    write_netcdf(convert(xarray.open_dataset('mesh_triangles.nc')),
                 'base_mesh.nc')

    print('Step 5. Inject correct meshDensity variable into base mesh file')
    inject_meshDensity(cw_filename=cw_filename,
                       mesh_filename='base_mesh.nc', on_sphere=on_sphere)

    if do_inject_bathymetry:
        print('Step 6. Injecting bathymetry')
        inject_bathymetry(mesh_file='base_mesh.nc')

    if preserve_floodplain:
        print('Step 7. Injecting flag to preserve floodplain')
        inject_preserve_floodplain(mesh_file='base_mesh.nc',
                                   floodplain_elevation=floodplain_elevation)

    print('Step 8. Create vtk file for visualization')
    extract_vtk(ignore_time=True, lonlat=True, dimension_list=['maxEdges='],
                variable_list=['allOnCells'], filename_pattern='base_mesh.nc',
                out_dir='base_mesh_vtk')

    print("***********************************************")
    print("**    The global mesh file is base_mesh.nc   **")
    print("***********************************************")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preserve_floodplain', action='store_true',
                        help='Whether a flood plain (bathymetry above z = 0) '
                             'should be preserved in the mesh')
    parser.add_argument('--floodplain_elevation', action='store',
                        type=float, default=20.0,
                        help='The elevation in meters to which the flood plain '
                             'is preserved, default is 20 m')
    parser.add_argument('--inject_bathymetry', action='store_true',
                        help='Whether one of the default bathymetry datasets, '
                             'earth_relief_15s.nc or topo.msh, should be added '
                             'to the MPAS mesh')
    parser.add_argument('--geometry', default='sphere',
                        help='Whether the mesh is on a sphere or a plane, '
                             'default is a sphere')
    parser.add_argument('--plot_cellWidth', action='store_true',
                        help='Whether to produce a plot of cellWidth')
    cl_args = parser.parse_args()
    build_mesh(cl_args.preserve_floodplain, cl_args.floodplain_elevation,
               cl_args.inject_bathymetry, cl_args.geometry,
               cl_args.plot_cellWidth)
