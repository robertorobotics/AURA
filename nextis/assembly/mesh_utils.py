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
    from OCP.BRepBndLib import BRepBndLib as brepbndlib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS as _topods_cast

    HAS_OCC = True
except ImportError:
    try:
        from OCC.Core.Bnd import Bnd_Box
        from OCC.Core.BRep import BRep_Tool
        from OCC.Core.BRepBndLib import brepbndlib
        from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
        from OCC.Core.TopAbs import TopAbs_FACE
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

    center = [
        round((xmin + xmax) / 2, 6),
        round((ymin + ymax) / 2, 6),
        round((zmin + zmax) / 2, 6),
    ]
    extents = [
        round(xmax - xmin, 6),
        round(ymax - ymin, 6),
        round(zmax - zmin, 6),
    ]
    bounds = [
        round(xmin, 6),
        round(ymin, 6),
        round(zmin, 6),
        round(xmax, 6),
        round(ymax, 6),
        round(zmax, 6),
    ]
    return center, extents, bounds


# ---------------------------------------------------------------------------
# Tessellation → GLB
# ---------------------------------------------------------------------------
def tessellate_to_glb(
    shape: Any,
    output_path: Path,
    linear_deflection: float = 0.001,
) -> bool:
    """Tessellate an OCC shape and export as GLB via trimesh.

    Args:
        shape: OCC TopoDS_Shape to tessellate.
        output_path: File path for the .glb output.
        linear_deflection: Mesh density (metres). Lower = finer.

    Returns:
        True if export succeeded, False otherwise.
    """
    if not HAS_TRIMESH:
        logger.warning("trimesh not installed, skipping GLB export")
        return False

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

                for i in range(1, nb_nodes + 1):
                    pt = triangulation.Node(i)
                    pt.Transform(trsf)
                    all_verts.append([pt.X(), pt.Y(), pt.Z()])

                for i in range(1, nb_tris + 1):
                    tri = triangulation.Triangle(i)
                    n1, n2, n3 = tri.Get()
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
            return False

        verts = np.array(all_verts, dtype=np.float64)
        faces = np.array(all_faces, dtype=np.int64)

        # Center vertices at local origin so Part.position is the sole placement.
        # OCC face transforms may include assembly-level placement, causing
        # double-positioning when the frontend also applies Part.position.
        centroid = verts.mean(axis=0)
        if np.linalg.norm(centroid) > 1e-6:
            verts -= centroid
            logger.debug(
                "Recentered %s by [%.6f, %.6f, %.6f]",
                output_path.name,
                centroid[0],
                centroid[1],
                centroid[2],
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
        mesh.export(str(output_path), file_type="glb")
        logger.debug(
            "Exported GLB: %s (%d verts, %d faces)",
            output_path.name,
            len(verts),
            len(faces),
        )
        return True

    except Exception as exc:
        logger.warning("GLB export failed for %s: %s", output_path.name, exc)
        return False
