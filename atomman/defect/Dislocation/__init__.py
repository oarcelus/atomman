# coding: utf-8
# Standard Python libraries
import io
from typing import Optional, Union
from itertools import product

# http://www.numpy.org/
import numpy as np
import numpy.typing as npt

# https://github.com/usnistgov/DataModelDict
from DataModelDict import DataModelDict as DM

from atomman.defect.VolterraDislocation import VolterraDislocation

# atomman imports
from .. import solve_volterra_dislocation
from ... import System, ElasticConstants
from ...tools import miller, vect_angle, boolean

class Dislocation():

    from ._monopole import monopole, cylinder_boundary, box_boundary
    from ._periodicarray import (periodicarray, array_boundary,
                                 build_disl_array)
    from ._dipole import dipole, dipole_displacement

    def __init__(self,
                 ucell: System,
                 C: ElasticConstants,
                 burgers: npt.ArrayLike,
                 ξ_uvw: npt.ArrayLike,
                 slip_hkl: npt.ArrayLike,
                 ucell_setting: str = 'p',
                 m: Union[str, npt.ArrayLike] = 'y',
                 n: Union[str, npt.ArrayLike] = 'z',
                 shift: Optional[npt.ArrayLike] = None,
                 shiftindex: Optional[int] = None,
                 shiftscale: Optional[bool] = None,
                 tol: float = 1e-8):
        """
        Class initializer.  Solves the dislocation solution and rotates the
        given unit cell to the proper orientation.

        Parameters
        ----------
        ucell : atomman.System
            The unit cell to use as the seed for generating the dislocation
            monopole system.
        C : atomman.ElasticConstants
            The elastic constants associated with the bulk crystal structure
            for ucell.
        burgers : array-like object
            The dislocation's Burgers vector given as a Miller or
            Miller-Bravais vector relative to ucell.
        ξ_uvw : array-like object
            The dislocation's line direction given as a Miller or
            Miller-Bravais vector relative to ucell.
        slip_hkl : array-like object
            The dislocation's slip plane given as a Miller or Miller-Bravais
            plane relative to ucell.
        ucell_setting : str, optional
            Indicates the space lattice setting of the given unit cell, i.e.
            p for primitive, i for body-centered, f for face-centered and
            a, b, or c for side-centered.  Setting this with the appropriate
            conventional unit cell allows for identifying lattice vectors that
            are not integers with respect to the conventional unit cell.  This
            also creates the rotated cell from a compatible primitive cell,
            thereby the final dislocation configurations can be smaller than
            possible solely from the conventional unit cell.
        m : str or array-like object, optional
            The Cartesian axis to align with the dislocation solution's m-axis,
            i.e. the in-plane direction perpendicular to the dislocation line.
            Can be specified as a 3D vector or str values 'x', 'y', or 'z'.  
            Default value is 'y' as this corresponds to the optimum alignment
            for LAMMPS systems.
        n : str or array-like object, optional
            The Cartesian axis to align with the dislocation solution's n-axis,
            i.e. the slip plane normal.  Can be specified as a 3D vector or str
            values 'x', 'y', or 'z'.  Default value is 'z' as this corresponds
            to the optimum alignment for LAMMPS systems.
        shift : array-like object, optional
            A rigid body shift to apply to the rotated cell prior to inserting
            the dislocation.  Should be selected such that the ideal slip plane
            does not correspond to any atomic planes.  Is taken as absolute if
            shiftscale is False, or relative to the rotated cell's box vectors
            if shiftscale is True.  Cannot be given with shiftindex.  If
            neither shift nor shiftindex is given then shiftindex = 0 is used.
        shiftindex : float, optional
            The index of the identified optimum shifts based on the rotated
            cell to use.  Different values allow for the selection of different
            atomic planes neighboring the slip plane.  Note that shiftindex
            values only apply shifts normal to the slip plane; best shifts for
            non-planar dislocations (like bcc screw) may also need a shift in
            the slip plane.  Cannot be given with shiftindex.  If neither shift
            nor shiftindex is given then shiftindex = 0 is used.
        shiftscale : bool, optional
            If False (default), a given shift value will be taken as absolute
            Cartesian.  If True, a given shift will be taken relative to the
            rotated cell's box vectors.
        tol : float
            A cutoff tolerance used with obtaining the dislocation solution.
            Only needs to be changed if there are issues with obtaining a
            solution.
        """
        # Generate the dislocation solution
        self.__dislsol = solve_volterra_dislocation(C, burgers, ξ_uvw=ξ_uvw,
                                                    slip_hkl=slip_hkl, m=m, n=n,
                                                    cart_axes=True, 
                                                    box=ucell.box, tol=tol)
        self.__transform = self.dislsol.transform

        # Build rcell and set orientation parameters
        self.__set_cells(ucell, ξ_uvw, setting=ucell_setting, maxindex=5)

        # Set shift value based on shift parameters
        self.__identify_shifts(tol)
        self.set_shift(shift, shiftindex, shiftscale)

        # Set base_system and disl_system to None
        self.__base_system = None
        self.__disl_system = None

    @classmethod
    def fromref(cls,
                ucell: System,
                C: ElasticConstants,
                model: Union[str, io.IOBase, DM],
                tol: float = 1e-8):
        """
        Initializes a Dislocation object based on pre-defined dislocation
        parameters from a reference record.

        Parameters
        ----------
        ucell : atomman.System
            The unit cell to use as the seed for generating the dislocation
            monopole system.
        C : atomman.ElasticConstants
            The elastic constants associated with the bulk crystal structure
            for ucell.
        model : str, file-like object or DataModelDict
            The reference record containing dislocation parameters to use.
        tol : float
            A cutoff tolerance used with obtaining the dislocation solution.
            Only needs to be changed if there are issues with obtaining a
            solution.
        """
        # Load the record
        model = DM(model).find('dislocation')

        # Extract the dislocation parameters
        cp = model['calculation-parameter']
        slip_hkl = np.array(cp['slip_hkl'].split(), dtype=int)
        ξ_uvw = np.array(cp['ξ_uvw'].split(), dtype=int)
        burgers = np.array(cp['burgers'].split(), dtype=float)
        m = np.array(cp.get('m', '0 1 0').split(), dtype=float)
        n = np.array(cp.get('n', '0 0 1').split(), dtype=float)

        shift = cp.get('shift', None)
        shiftindex = cp.get('shiftindex', None)
        shiftscale = boolean(cp.get('shiftscale', False))

        if shift is not None:
            shift = np.array(shift.split(), dtype='float')
        elif shiftindex is not None:
            shiftindex = int(shiftindex)

        return cls(ucell, C, burgers, ξ_uvw, slip_hkl, m=m, n=n, shift=shift,
                   shiftindex=shiftindex, shiftscale=shiftscale, tol=tol)

    @property
    def dislsol(self) -> VolterraDislocation:
        """atomman.defect.VolterraDislocation : The elastic dislocation solution"""
        return self.__dislsol

    @property
    def uvws(self) -> np.ndarray:
        """numpy.NDArray : The 3x3 array of uvw Miller vectors that correspond to the rcell orientation"""
        return self.__uvws

    @property
    def uvws_prim(self) -> np.ndarray:
        """numpy.NDArray : The 3x3 array of uvw Miller vectors used to rotate ucell_prim to rcell"""
        return self.__uvws_prim

    @property
    def transform(self) -> np.ndarray:
        """numpy.NDArray : The 3x3 Cartesian transformation matrix associated with rotating from ucell to rcell"""
        return self.__transform

    @property
    def ucell(self) -> System:
        """atomman.System : The reference conventional unit cell for the dislocation system"""
        return self.__ucell

    @property
    def ucell_prim(self) -> System:
        """atomman.System : The primitive unit cell of ucell used as the basis for constructing rcell"""
        return self.__ucell_prim

    @property
    def rcell(self) -> System:
        """atomman.System : The rotated cell that coincides with the dislocation solution orientation"""
        return self.__rcell

    @property
    def lineindex(self) -> int:
        """int : The index of the box vector that coincides with the dislocation line: 0=a, 1=b, 2=c"""
        return self.__lineindex

    @property
    def cutindex(self) -> int:
        """int : The index of the box vector that is not within the slip plane: 0=a, 1=b, 2=c"""
        return self.__cutindex

    @property
    def motionindex(self) -> int:
        """int : The index of the box vector that is not the line or cut directions: 0=a, 1=b, 2=c"""
        return self.__motionindex

    @property
    def shifts(self) -> list:
        """list : All identified shifts that will place the slip plane halfway between atomic planes"""
        return self.__shifts

    @property
    def shift(self) -> np.ndarray:
        """numpy.NDArray : The particular shift value that will be or was used to construct the dislocation system"""
        return self.__shift

    @property
    def base_system(self) -> System:
        """atomman.System : The "perfect crystal" reference system associated with the dislocation system"""
        if self.__base_system is not None:
            return self.__base_system
        else:
            raise ValueError('base_system not built yet: must call monopole() or periodicarray() first')

    @property
    def disl_system(self) -> System:
        """atomman.System : The generated dislocation system"""
        if self.__disl_system is not None:
            return self.__disl_system
        else:
            raise ValueError('disl_system not built yet: must call monopole() or periodicarray() first')

    def __set_cells(self, ucell, ξ_uvw, setting, maxindex=5):

        # Extract dislsol
        dislsol = self.dislsol

        # Get primitive cell and associated transformation matrix
        ucell_prim, c2p_transform = ucell.dump('conventional_to_primitive', setting=setting,
                                                return_transform=True)

        # Convert ξ_uvw to the primitive cell
        ξ_uvw_p = miller.vector_conventional_to_primitive(ξ_uvw, setting=setting)

        # Get Cartesian m, n axes relative to ucell_prim
        m_cart = c2p_transform.dot(dislsol.m.dot(dislsol.transform))
        n_cart = c2p_transform.dot(dislsol.n.dot(dislsol.transform))

        # Generate an array of all int uvws with abs(u, v, w) <= maxindex
        alluvws = np.array([p for p in product(range(-maxindex, maxindex+1), repeat=3)])
        alluvws = alluvws[np.abs(alluvws).sum(axis=1) != 0]  # Remove [0, 0, 0]

        # Convert alluvws to Cartesian wrt the primitive ucell box
        alluvws_cart = ucell_prim.box.vector_crystal_to_cartesian(alluvws)

        # Compute the angles between alluvws and the m, n axes
        m_angle = vect_angle(alluvws_cart, m_cart)
        n_angle = vect_angle(alluvws_cart, n_cart)

        # Find in-plane uvw closest to m
        inplane_uvws = alluvws[np.isclose(n_angle, 90.0)]
        inplane_m_angle = m_angle[np.isclose(n_angle, 90.0)]
        m_uvw = inplane_uvws[np.isclose(inplane_m_angle, inplane_m_angle.min())]
        if len(m_uvw) > 0:
            m_uvw = m_uvw[0] / np.gcd.reduce(np.asarray(m_uvw[0], dtype=int)) 
        else:
            raise ValueError('Failed to find vector near edge component direction')

        # Find uvw closest to n
        n_uvw = alluvws[np.isclose(n_angle, n_angle.min())]
        if len(n_uvw) > 0:
            n_uvw = n_uvw[0] / np.gcd.reduce(np.asarray(n_uvw[0], dtype=int)) 
        else:
            raise ValueError('Failed to find vector near slip plane normal')

        # Identify lineindex and cutindex
        indices = np.array([0, 1, 2])
        cutindex = indices[np.isclose(np.abs(dislsol.n), 1.0)][0]
        lineindex = indices[np.isclose(np.abs(dislsol.ξ), 1.0)][0]
        if cutindex == lineindex:
            raise RuntimeError('Encountered cutindex == lineindex: should not be possible!')

        # Orient the uvw sets based on cutboxvector and ξboxvector
        if cutindex == 2:
            if lineindex == 0:
                uvws = np.array([ξ_uvw_p, m_uvw, n_uvw])
            else:
                uvws = np.array([-m_uvw, ξ_uvw_p, n_uvw])

        elif cutindex == 1:
            if lineindex == 2:
                uvws = np.array([m_uvw, n_uvw, ξ_uvw_p])
            else:
                uvws = np.array([ξ_uvw_p, n_uvw, -m_uvw])

        elif cutindex == 0:
            if lineindex == 1:
                uvws = np.array([n_uvw, ξ_uvw_p, m_uvw])
            else:
                uvws = np.array([n_uvw, -m_uvw, ξ_uvw_p])

        # Generate rcell
        rcell = ucell_prim.rotate(uvws)

        # Save cells and orientation parameters as object attributes
        self.__ucell = ucell
        self.__ucell_prim = ucell_prim
        self.__rcell = rcell

        self.__uvws = miller.vector_primitive_to_conventional(uvws, setting=setting)
        self.__uvws_prim = uvws
        self.__lineindex = lineindex
        self.__cutindex = cutindex
        self.__motionindex = 3 - (lineindex + cutindex)

    def __identify_shifts(self, tol):

        # Define out of plane unit vector
        ovect = self.dislsol.n

        # Get out of plane width
        rcellwidth = self.rcell.box.vects[self.cutindex, self.cutindex]

        # Get the unique coordinates normal to the plane
        pos = self.rcell.atoms.pos
        numdec = - int(np.floor(np.log10(tol)))
        coords = np.unique(pos[:, self.cutindex].round(numdec))

        # Add periodic replica if missing
        if not np.isclose(coords[-1] - coords[0], rcellwidth, rtol=0.0, atol=tol):
            coords = np.append(coords, coords[0] + rcellwidth)

        # Compute the shifts
        relshifts = rcellwidth - (coords[1:] + coords[:-1]) / 2
        relshifts[relshifts > rcellwidth] -= rcellwidth
        relshifts[relshifts < 0.0] += rcellwidth
        self.__shifts = np.outer(np.sort(relshifts), ovect)

    def set_shift(self, shift, shiftindex, shiftscale):
        # Handle shift parameters
        if shift is not None:
            if shiftindex is not None:
                raise ValueError('shift and shiftindex cannot both be given')
            if shiftscale is True:
                self.__shift = miller.vector_crystal_to_cartesian(shift, self.rcell.box)
            else:
                self.__shift = np.asarray(shift)
                assert self.__shift.shape == (3,)
        elif shiftindex is not None:
            self.__shift = self.shifts[shiftindex]
        else:
            self.__shift = self.shifts[0]

    def set_systems(self, base_system, disl_system):
        self.__base_system = base_system
        self.__disl_system = disl_system
