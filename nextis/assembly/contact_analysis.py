"""Contact detection and geometric classification for assembly parts.

Extracted from cad_parser.py to respect the 500-line file limit.
Analyzes inter-part contacts using BRepExtrema and classifies the
contact type (coaxial, planar, point, line, complex) using dominant
face analysis on each shape's B-rep faces.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from nextis.assembly.models import ContactInfo, ContactType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional OCC imports — try OCP (pip) first, then OCC.Core (conda)
# ---------------------------------------------------------------------------
try:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import (
        GeomAbs_Cone,
        GeomAbs_Cylinder,
        GeomAbs_Plane,
        GeomAbs_Sphere,
        GeomAbs_Torus,
    )
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS as _topods_cast

    HAS_OCC = True
except ImportError:
    try:
        from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
        from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
        from OCC.Core.BRepGProp import BRepGProp
        from OCC.Core.GeomAbs import (
            GeomAbs_Cone,
            GeomAbs_Cylinder,
            GeomAbs_Plane,
            GeomAbs_Sphere,
            GeomAbs_Torus,
        )
        from OCC.Core.GProp import GProp_GProps
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCC.Core.TopExp import TopExp_Explorer

        _topods_cast = None  # pythonocc auto-downcasts
        HAS_OCC = True
    except ImportError:
        HAS_OCC = False
        _topods_cast = None

# Face type enum → string mapping (populated only when OCC is available)
_TYPE_MAP: dict[Any, str] = {}
if HAS_OCC:
    _TYPE_MAP = {
        GeomAbs_Plane: "plane",
        GeomAbs_Cylinder: "cylinder",
        GeomAbs_Sphere: "sphere",
        GeomAbs_Cone: "cone",
        GeomAbs_Torus: "torus",
    }


def _static(cls: Any, method: str) -> Any:
    """Get a static method from an OCC class, trying OCP '_s' suffix first."""
    return getattr(cls, f"{method}_s", None) or getattr(cls, method)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_contacts(
    parts: list[Any],
    contact_tolerance: float = 0.0002,
    unit_scale: float = 1.0,
) -> list[ContactInfo]:
    """Find pairs of parts in contact and classify the contact geometry.

    Performs O(n^2) pairwise BRepExtrema distance checks. For each pair
    within tolerance, extracts closest points and classifies the contact
    type using dominant face analysis on each shape.

    Args:
        parts: Objects with ``.part_id`` (str) and ``.shape`` (TopoDS_Shape).
        contact_tolerance: Max distance (metres) to consider parts in contact.
        unit_scale: Factor to convert shape coordinates to metres.

    Returns:
        List of ContactInfo objects for all detected contacts.
    """
    if not HAS_OCC:
        logger.warning("OCC not available — skipping contact detection")
        return []

    contacts: list[ContactInfo] = []
    n = len(parts)
    for i in range(n):
        for j in range(i + 1, n):
            try:
                info = _analyze_pair(parts[i], parts[j], contact_tolerance, unit_scale)
                if info is not None:
                    contacts.append(info)
            except Exception as exc:
                logger.debug(
                    "Contact check failed for %s/%s: %s",
                    parts[i].part_id,
                    parts[j].part_id,
                    exc,
                )
    logger.info("Detected %d contact pair(s) among %d parts", len(contacts), n)
    return contacts


# ---------------------------------------------------------------------------
# Per-pair analysis
# ---------------------------------------------------------------------------


def _analyze_pair(
    part_a: Any,
    part_b: Any,
    tolerance: float,
    unit_scale: float,
) -> ContactInfo | None:
    """Analyze a single part pair for contact and classify geometry.

    Returns None if the pair is not in contact (distance >= tolerance).
    """
    dist_tool = BRepExtrema_DistShapeShape(part_a.shape, part_b.shape)
    if not dist_tool.IsDone():
        return None

    distance = dist_tool.Value()
    if distance >= tolerance:
        return None

    # Extract closest points (OCC native coordinates)
    pt_a = dist_tool.PointOnShape1(1)
    pt_b = dist_tool.PointOnShape2(1)

    # Convert to Y-up coordinates (matching Part.position convention)
    point_a = _occ_point_to_yup(pt_a, unit_scale)
    point_b = _occ_point_to_yup(pt_b, unit_scale)
    normal = _compute_contact_normal(pt_a, pt_b)

    # Classify using dominant face type per shape (simplification heuristic)
    face_type_a = _find_dominant_face_type(part_a.shape)
    face_type_b = _find_dominant_face_type(part_b.shape)
    contact_type = _classify_contact_type(face_type_a, face_type_b)

    # Derive insertion axis and area class
    insertion_axis = _derive_insertion_axis(
        contact_type, face_type_a, face_type_b, part_a.shape, part_b.shape
    )
    area_class = _compute_area_class(part_a.shape, part_b.shape, unit_scale)

    # Canonical ordering: part_a < part_b lexicographically
    id_a, id_b = part_a.part_id, part_b.part_id
    if id_a > id_b:
        id_a, id_b = id_b, id_a
        point_a, point_b = point_b, point_a
        normal = [-c for c in normal]
        if insertion_axis is not None:
            insertion_axis = [-c for c in insertion_axis]

    logger.debug(
        "Contact: %s <-> %s (dist=%.6f, type=%s)",
        id_a,
        id_b,
        distance,
        contact_type.value,
    )

    return ContactInfo(
        part_a=id_a,
        part_b=id_b,
        distance=round(distance * unit_scale, 8),
        normal=normal,
        contact_point_a=point_a,
        contact_point_b=point_b,
        contact_type=contact_type,
        insertion_axis=insertion_axis,
        clearance_mm=None,
        area_class=area_class,
    )


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------


def _occ_point_to_yup(pt: Any, unit_scale: float) -> list[float]:
    """Convert an OCC gp_Pnt (Z-up) to Three.js Y-up coordinates in metres."""
    return [
        round(pt.X() * unit_scale, 6),
        round(pt.Z() * unit_scale, 6),
        round(-pt.Y() * unit_scale, 6),
    ]


def _compute_contact_normal(pt_a: Any, pt_b: Any) -> list[float]:
    """Compute unit normal from pt_a toward pt_b, in Y-up coords.

    Falls back to [0, 1, 0] (upward) if points are coincident.
    """
    # Convert to Y-up before computing direction
    dx = pt_b.X() - pt_a.X()
    dy = pt_b.Z() - pt_a.Z()
    dz = -(pt_b.Y() - pt_a.Y())
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-12:
        return [0.0, 1.0, 0.0]
    return [round(dx / length, 6), round(dy / length, 6), round(dz / length, 6)]


# ---------------------------------------------------------------------------
# Dominant face type analysis
# ---------------------------------------------------------------------------


def _find_dominant_face_type(shape: Any) -> str:
    """Find the B-rep face type with the largest surface area.

    This is an intentional simplification (~80% accuracy). Using the
    dominant face type per part rather than the exact face at the
    closest point is more robust against tessellation artifacts.

    Args:
        shape: OCC TopoDS_Shape.

    Returns:
        One of "plane", "cylinder", "sphere", "cone", "torus", or "other".
    """
    if not HAS_OCC:
        return "other"

    best_area = 0.0
    best_type = "other"

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        if _topods_cast is not None:
            face = _static(_topods_cast, "Face")(face)

        try:
            surf = BRepAdaptor_Surface(face, True)
            face_type_enum = surf.GetType()

            props = GProp_GProps()
            _static(BRepGProp, "SurfaceProperties")(face, props)
            area = props.Mass()

            if area > best_area:
                best_area = area
                best_type = _TYPE_MAP.get(face_type_enum, "other")
        except Exception:
            pass

        explorer.Next()

    return best_type


# ---------------------------------------------------------------------------
# Contact type classification
# ---------------------------------------------------------------------------


def _classify_contact_type(face_type_a: str, face_type_b: str) -> ContactType:
    """Classify the contact type from the dominant face types of two parts.

    Heuristic rules:
        cylinder + cylinder  -> COAXIAL  (shafts, bearings, pins)
        cylinder/cone + cone -> COAXIAL  (tapered fits)
        plane + plane        -> PLANAR   (flat face-to-face)
        sphere + anything    -> POINT    (ball-in-socket, ball-on-face)
        cylinder + plane     -> LINE     (shaft resting on flat)
        cone + plane         -> LINE
        all other combos     -> COMPLEX
    """
    pair = frozenset({face_type_a, face_type_b})

    if pair == frozenset({"cylinder"}):
        return ContactType.COAXIAL
    if pair in (frozenset({"cylinder", "cone"}), frozenset({"cone"})):
        return ContactType.COAXIAL
    if pair == frozenset({"plane"}):
        return ContactType.PLANAR
    if "sphere" in pair:
        return ContactType.POINT
    if pair in (frozenset({"cylinder", "plane"}), frozenset({"cone", "plane"})):
        return ContactType.LINE
    return ContactType.COMPLEX


# ---------------------------------------------------------------------------
# Insertion axis derivation
# ---------------------------------------------------------------------------


def _derive_insertion_axis(
    contact_type: ContactType,
    face_type_a: str,
    face_type_b: str,
    shape_a: Any,
    shape_b: Any,
) -> list[float] | None:
    """Derive the insertion axis for coaxial or planar contacts.

    For coaxial: extracts the cylinder axis from the dominant cylindrical face.
    For planar: uses the face normal of the largest planar face.
    For others: returns None.
    """
    if contact_type == ContactType.COAXIAL:
        target = shape_a if face_type_a == "cylinder" else shape_b
        return _extract_cylinder_axis(target)
    if contact_type == ContactType.PLANAR:
        target = shape_a if face_type_a == "plane" else shape_b
        return _extract_plane_normal(target)
    return None


def _extract_cylinder_axis(shape: Any) -> list[float] | None:
    """Extract axis direction of the largest cylindrical face, in Y-up coords."""
    if not HAS_OCC:
        return None

    best_area = 0.0
    best_axis: list[float] | None = None

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        if _topods_cast is not None:
            face = _static(_topods_cast, "Face")(face)

        try:
            surf = BRepAdaptor_Surface(face, True)
            if surf.GetType() == GeomAbs_Cylinder:
                props = GProp_GProps()
                _static(BRepGProp, "SurfaceProperties")(face, props)
                area = props.Mass()
                if area > best_area:
                    best_area = area
                    direction = surf.Cylinder().Axis().Direction()
                    # OCC Z-up → Y-up: [dx, dz, -dy]
                    best_axis = [
                        round(direction.X(), 6),
                        round(direction.Z(), 6),
                        round(-direction.Y(), 6),
                    ]
        except Exception:
            pass

        explorer.Next()

    return best_axis


def _extract_plane_normal(shape: Any) -> list[float] | None:
    """Extract normal of the largest planar face, in Y-up coords."""
    if not HAS_OCC:
        return None

    best_area = 0.0
    best_normal: list[float] | None = None

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        if _topods_cast is not None:
            face = _static(_topods_cast, "Face")(face)

        try:
            surf = BRepAdaptor_Surface(face, True)
            if surf.GetType() == GeomAbs_Plane:
                props = GProp_GProps()
                _static(BRepGProp, "SurfaceProperties")(face, props)
                area = props.Mass()
                if area > best_area:
                    best_area = area
                    normal = surf.Plane().Axis().Direction()
                    if face.Orientation() == TopAbs_REVERSED:
                        normal.Reverse()
                    # OCC Z-up → Y-up: [nx, nz, -ny]
                    best_normal = [
                        round(normal.X(), 6),
                        round(normal.Z(), 6),
                        round(-normal.Y(), 6),
                    ]
        except Exception:
            pass

        explorer.Next()

    return best_normal


# ---------------------------------------------------------------------------
# Area classification
# ---------------------------------------------------------------------------


def _compute_area_class(
    shape_a: Any,
    shape_b: Any,
    unit_scale: float,
) -> str | None:
    """Classify contact area as 'large', 'medium', or 'small'.

    Uses the smaller of the two shapes' dominant face areas as proxy.
    Thresholds in mm^2: large > 100, medium > 10, small <= 10.

    Args:
        shape_a: First OCC TopoDS_Shape.
        shape_b: Second OCC TopoDS_Shape.
        unit_scale: Factor to convert shape coordinates to metres.

    Returns:
        Area class string, or None if computation fails.
    """
    if not HAS_OCC:
        return None

    area_a = _largest_face_area(shape_a)
    area_b = _largest_face_area(shape_b)

    if area_a is None or area_b is None:
        return None

    # Use the smaller area as the contact area proxy, convert to mm²
    area_mm2 = min(area_a, area_b) * (unit_scale**2) * 1e6

    if area_mm2 > 100.0:
        return "large"
    if area_mm2 > 10.0:
        return "medium"
    return "small"


def _largest_face_area(shape: Any) -> float | None:
    """Return the area of the largest face on a shape (in native OCC units)."""
    best_area = 0.0
    found = False

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        if _topods_cast is not None:
            face = _static(_topods_cast, "Face")(face)

        try:
            props = GProp_GProps()
            _static(BRepGProp, "SurfaceProperties")(face, props)
            area = props.Mass()
            if area > best_area:
                best_area = area
                found = True
        except Exception:
            pass

        explorer.Next()

    return best_area if found else None
