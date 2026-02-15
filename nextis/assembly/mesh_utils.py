"""Mesh utilities: tessellation, geometry classification, and GLB export.

Helpers used by CADParser to convert OCC shapes into trimesh meshes and
classify bounding boxes into placeholder geometry types for the frontend.
"""

from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports — try OCP (pip: cadquery-ocp) first, then OCC (conda)
# ---------------------------------------------------------------------------
try:
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib as brepbndlib
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS as _topods_cast

    HAS_OCC = True
except ImportError:
    try:
        from OCC.Core.Bnd import Bnd_Box
        from OCC.Core.BRep import BRep_Tool
        from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
        from OCC.Core.BRepBndLib import brepbndlib
        from OCC.Core.BRepGProp import BRepGProp
        from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
        from OCC.Core.GeomAbs import GeomAbs_Plane
        from OCC.Core.GProp import GProp_GProps
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopLoc import TopLoc_Location

        _topods_cast = None  # pythonocc auto-downcasts
        HAS_OCC = True
    except ImportError:
        HAS_OCC = False
        _topods_cast = None

try:
    import trimesh

    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False


def _static(cls: Any, method: str) -> Any:
    """Get a static method from an OCC class, trying OCP '_s' suffix first."""
    return getattr(cls, f"{method}_s", None) or getattr(cls, method)


# ---------------------------------------------------------------------------
# Colour palette for parts
# ---------------------------------------------------------------------------
_PART_COLORS = [
    "#B0AEA8",
    "#8A8884",
    "#D4D3CF",
    "#7A7974",
    "#C4A882",
    "#9CABA3",
    "#A89080",
    "#B8B0A0",
    "#8C9488",
    "#C0B8B0",
]


def color_for_part(name: str, index: int) -> str:
    """Return a deterministic hex colour for a part."""
    h = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)  # noqa: S324
    return _PART_COLORS[(h + index) % len(_PART_COLORS)]


# ---------------------------------------------------------------------------
# Geometry classification
# ---------------------------------------------------------------------------
def classify_geometry(
    dx: float,
    dy: float,
    dz: float,
) -> tuple[str, list[float]]:
    """Classify bounding box into placeholder geometry type.

    Args:
        dx: Width in metres.
        dy: Height in metres.
        dz: Depth in metres.

    Returns:
        Tuple of (geometry_type, dimensions) for the frontend PartMesh.
    """
    sorted_dims = sorted([dx, dy, dz])
    ratio = sorted_dims[2] / max(sorted_dims[0], 1e-9)

    # Equidimensional → sphere
    if ratio < 1.3 and sorted_dims[1] / max(sorted_dims[0], 1e-9) < 1.3:
        radius = max(dx, dy, dz) / 2
        return "sphere", [radius]

    # One axis much longer, other two similar → cylinder
    if ratio > 2.0 and sorted_dims[1] / max(sorted_dims[0], 1e-9) < 1.5:
        radius = (sorted_dims[0] + sorted_dims[1]) / 4
        height = sorted_dims[2]
        return "cylinder", [radius, height]

    return "box", [dx, dy, dz]


# ---------------------------------------------------------------------------
# Transform extraction
# ---------------------------------------------------------------------------
def trsf_to_pos_rot(trsf: Any) -> tuple[list[float], list[float]]:
    """Extract position and Euler angles (XYZ) from a gp_Trsf.

    Args:
        trsf: OCC gp_Trsf transformation.

    Returns:
        ([x, y, z], [rx, ry, rz]) position in metres, rotation in radians.
    """
    tx = trsf.Value(1, 4)
    ty = trsf.Value(2, 4)
    tz = trsf.Value(3, 4)

    # Rotation matrix → Euler XYZ
    r11 = trsf.Value(1, 1)
    r21 = trsf.Value(2, 1)
    r31 = trsf.Value(3, 1)
    r32 = trsf.Value(3, 2)
    r33 = trsf.Value(3, 3)

    ry = math.asin(max(-1.0, min(1.0, -r31)))
    if abs(math.cos(ry)) > 1e-6:
        rx = math.atan2(r32, r33)
        rz = math.atan2(r21, r11)
    else:
        rx = math.atan2(-trsf.Value(2, 3), trsf.Value(2, 2))
        rz = 0.0

    return (
        [round(tx, 6), round(ty, 6), round(tz, 6)],
        [round(rx, 6), round(ry, 6), round(rz, 6)],
    )


# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------
def compute_bounding_box(
    shape: Any,
) -> tuple[list[float], list[float], list[float]]:
    """Compute bounding box center, extents, and min/max corners.

    Args:
        shape: OCC TopoDS_Shape.

    Returns:
        (center_xyz, extents_xyz, [xmin, ymin, zmin, xmax, ymax, zmax])
    """
    box = Bnd_Box()
    _static(brepbndlib, "Add")(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()

    # Convert OCC Z-up to Three.js Y-up: new_Y = old_Z, new_Z = -old_Y
    center = [
        round((xmin + xmax) / 2, 6),
        round((zmin + zmax) / 2, 6),
        round(-(ymin + ymax) / 2, 6),
    ]
    extents = [
        round(xmax - xmin, 6),
        round(zmax - zmin, 6),
        round(ymax - ymin, 6),
    ]
    bounds = [
        round(xmin, 6),
        round(zmin, 6),
        round(-ymax, 6),
        round(xmax, 6),
        round(zmax, 6),
        round(-ymin, 6),
    ]
    return center, extents, bounds


# ---------------------------------------------------------------------------
# Resting orientation
# ---------------------------------------------------------------------------
def _normal_to_down_euler(normal: tuple[float, float, float]) -> list[float]:
    """Compute Euler XYZ angles to rotate a normal vector to point -Y (down).

    Uses Rodrigues' rotation: find the axis and angle that maps the face
    normal to [0, -1, 0], then decompose to Euler XYZ.  The decomposition
    matches ``trsf_to_pos_rot`` exactly.

    Args:
        normal: Unit normal vector (nx, ny, nz) of the face to place down.

    Returns:
        [rx, ry, rz] in radians.
    """
    nx, ny, nz = normal
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-9:
        return [0.0, 0.0, 0.0]
    nx, ny, nz = nx / length, ny / length, nz / length

    # dot(normal, [0, -1, 0]) = -ny
    dot = -ny
    if dot > 0.9999:
        return [0.0, 0.0, 0.0]
    if dot < -0.9999:
        return [round(math.pi, 6), 0.0, 0.0]

    # cross(normal, [0, -1, 0]) = [nz, 0, -nx]  (ay=0)
    ax, az = nz, -nx
    axis_len = math.sqrt(ax * ax + az * az)
    if axis_len < 1e-9:
        return [0.0, 0.0, 0.0]
    ax /= axis_len
    az /= axis_len

    angle = math.acos(max(-1.0, min(1.0, dot)))
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1.0 - c

    # Rotation matrix with ay=0
    r11 = t * ax * ax + c
    r21 = s * az
    r22 = c
    r23 = -s * ax
    r31 = t * az * ax
    r32 = s * ax
    r33 = t * az * az + c

    # Euler XYZ — same convention as trsf_to_pos_rot
    ry = math.asin(max(-1.0, min(1.0, -r31)))
    if abs(math.cos(ry)) > 1e-6:
        rx = math.atan2(r32, r33)
        rz = math.atan2(r21, r11)
    else:
        rx = math.atan2(-r23, r22)
        rz = 0.0

    return [round(rx, 6), round(ry, 6), round(rz, 6)]


def compute_resting_rotation(shape: Any) -> list[float]:
    """Compute Euler XYZ rotation to rest a shape on its largest flat face.

    Iterates all faces of the shape, finds the largest planar face, and
    computes the rotation that aligns that face's outward normal to -Y
    (pointing down), so the part rests stably on the work surface.

    Args:
        shape: OCC TopoDS_Shape to analyze.

    Returns:
        [rx, ry, rz] Euler angles in radians.  [0, 0, 0] if no planar
        face is found or on error.
    """
    if not HAS_OCC:
        return [0.0, 0.0, 0.0]

    try:
        best_area = 0.0
        best_normal: tuple[float, float, float] = (0.0, -1.0, 0.0)

        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = explorer.Current()
            # OCP requires explicit downcast; pythonocc auto-downcasts
            if _topods_cast is not None:
                face = _static(_topods_cast, "Face")(face)
            surf = BRepAdaptor_Surface(face, True)

            if surf.GetType() == GeomAbs_Plane:
                props = GProp_GProps()
                _static(BRepGProp, "SurfaceProperties")(face, props)
                area = props.Mass()

                if area > best_area:
                    best_area = area
                    plane = surf.Plane()
                    normal = plane.Axis().Direction()
                    if face.Orientation() == TopAbs_REVERSED:
                        normal.Reverse()
                    best_normal = (normal.X(), normal.Y(), normal.Z())

            explorer.Next()

        if best_area < 1e-12:
            return [0.0, 0.0, 0.0]

        # Convert normal from OCC Z-up to Three.js Y-up: [nx, ny, nz] → [nx, nz, -ny]
        nx, ny, nz = best_normal
        best_normal = (nx, nz, -ny)

        return _normal_to_down_euler(best_normal)

    except Exception as exc:
        logger.warning("Resting rotation computation failed: %s", exc)
        return [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# Tessellation → GLB
# ---------------------------------------------------------------------------
def tessellate_to_glb(
    shape: Any,
    output_path: Path,
    linear_deflection: float = 0.001,
    unit_scale: float = 1.0,
) -> tuple[bool, list[float]]:
    """Tessellate an OCC shape and export as GLB via trimesh.

    The mesh is centered at local origin (bbox center subtracted).  All
    vertex data is scaled by *unit_scale* so the output GLB always contains
    metre-scale geometry.  Returns the bbox center (in metres) so the
    caller can reconstruct the world position.

    Args:
        shape: OCC TopoDS_Shape to tessellate.
        output_path: File path for the .glb output.
        linear_deflection: Mesh density (metres). Lower = finer.
        unit_scale: Factor to convert source coordinates to metres.
            1.0 for files already in metres, 0.001 for files in mm.

    Returns:
        Tuple of (success, bbox_center_xyz).  bbox_center_xyz is the
        bounding box center in metres, or [0, 0, 0] if tessellation failed.
    """
    if not HAS_TRIMESH:
        logger.warning("trimesh not installed, skipping GLB export")
        return False, [0.0, 0.0, 0.0]

    try:
        BRepMesh_IncrementalMesh(shape, linear_deflection)

        all_verts: list[list[float]] = []
        all_faces: list[list[int]] = []
        offset = 0

        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = explorer.Current()
            # OCP requires explicit downcast; pythonocc auto-downcasts
            if _topods_cast is not None:
                face = _static(_topods_cast, "Face")(face)
            loc = TopLoc_Location()
            triangulation = _static(BRep_Tool, "Triangulation")(face, loc)

            if triangulation is not None:
                trsf = loc.Transformation()
                nb_nodes = triangulation.NbNodes()
                nb_tris = triangulation.NbTriangles()

                # Reversed faces have inward normals — flip winding to fix
                is_reversed = face.Orientation() == TopAbs_REVERSED

                for i in range(1, nb_nodes + 1):
                    pt = triangulation.Node(i)
                    pt.Transform(trsf)
                    all_verts.append([pt.X(), pt.Y(), pt.Z()])

                for i in range(1, nb_tris + 1):
                    tri = triangulation.Triangle(i)
                    n1, n2, n3 = tri.Get()
                    if is_reversed:
                        n1, n2 = n2, n1
                    all_faces.append(
                        [
                            n1 - 1 + offset,
                            n2 - 1 + offset,
                            n3 - 1 + offset,
                        ]
                    )

                offset += nb_nodes

            explorer.Next()

        if not all_verts or not all_faces:
            logger.warning(
                "Tessellation produced no geometry for %s",
                output_path.name,
            )
            return False, [0.0, 0.0, 0.0]

        verts = np.array(all_verts, dtype=np.float64)
        faces = np.array(all_faces, dtype=np.int64)

        # Convert source units to metres before any further processing.
        if abs(unit_scale - 1.0) > 1e-9:
            verts *= unit_scale

        # Convert OCC Z-up to Three.js Y-up: [x, y, z] → [x, z, -y]
        verts_y = verts[:, 1].copy()
        verts[:, 1] = verts[:, 2]
        verts[:, 2] = -verts_y

        # Center vertices at local origin so Part.position is the sole placement.
        # Use bounding box center (not vertex mean) to avoid position drift
        # on parts with non-uniform mesh density (gears, holes, etc.).
        bbox_center = (verts.min(axis=0) + verts.max(axis=0)) / 2
        bbox_center_list = [round(float(c), 6) for c in bbox_center]
        if np.linalg.norm(bbox_center) > 1e-6:
            verts -= bbox_center
            logger.debug(
                "Recentered %s by [%.6f, %.6f, %.6f]",
                output_path.name,
                bbox_center[0],
                bbox_center[1],
                bbox_center[2],
            )

        bbox_min = verts.min(axis=0)
        bbox_max = verts.max(axis=0)
        logger.debug(
            "Post-center bbox for %s: min=[%.3f, %.3f, %.3f] max=[%.3f, %.3f, %.3f]",
            output_path.name,
            *bbox_min,
            *bbox_max,
        )

        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        trimesh.repair.fix_normals(mesh)
        mesh.export(str(output_path), file_type="glb")
        logger.debug(
            "Exported GLB: %s (%d verts, %d faces, watertight=%s)",
            output_path.name,
            len(verts),
            len(faces),
            mesh.is_watertight,
        )
        return True, bbox_center_list

    except Exception as exc:
        logger.warning("GLB export failed for %s: %s", output_path.name, exc)
        return False, [0.0, 0.0, 0.0]
