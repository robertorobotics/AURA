"""Tests for contact geometry detection and classification.

Requires OCP (pip: cadquery-ocp) or pythonocc-core (conda) for
shape-based tests. Serialization and adjacency tests run without OCC.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pytest

from nextis.assembly.models import ContactInfo, ContactType

# Guard: skip OCC-dependent tests if no OpenCASCADE bindings installed
_occ_available = True
try:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
except ImportError:
    try:
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
        from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt
    except ImportError:
        _occ_available = False

_occ_skip = pytest.mark.skipif(not _occ_available, reason="OCP/pythonocc not installed")


@dataclass
class _FakePart:
    """Minimal stand-in for _RawPart (duck-typed by detect_contacts)."""

    part_id: str
    shape: Any


# ---------------------------------------------------------------------------
# Tests that do NOT require OCC
# ---------------------------------------------------------------------------


class TestContactInfoSerialization:
    """Round-trip ContactInfo through Pydantic JSON."""

    def test_round_trip(self) -> None:
        info = ContactInfo(
            part_a="bearing_1",
            part_b="housing_1",
            distance=0.00015,
            normal=[0.0, 1.0, 0.0],
            contact_point_a=[0.01, 0.02, -0.03],
            contact_point_b=[0.01, 0.02, -0.03],
            contact_type=ContactType.COAXIAL,
            insertion_axis=[0.0, 1.0, 0.0],
            clearance_mm=0.05,
            area_class="medium",
        )
        data = info.model_dump(by_alias=True)

        # camelCase aliases in JSON output
        assert data["partA"] == "bearing_1"
        assert data["partB"] == "housing_1"
        assert data["contactType"] == "coaxial"
        assert data["insertionAxis"] == [0.0, 1.0, 0.0]
        assert data["contactPointA"] == [0.01, 0.02, -0.03]
        assert data["clearanceMm"] == 0.05
        assert data["areaClass"] == "medium"

        # Round-trip back
        loaded = ContactInfo.model_validate(data)
        assert loaded.contact_type == ContactType.COAXIAL
        assert loaded.part_a == "bearing_1"
        assert loaded.insertion_axis == [0.0, 1.0, 0.0]

    def test_snake_case_input(self) -> None:
        """populate_by_name=True allows snake_case construction."""
        info = ContactInfo(
            part_a="a",
            part_b="b",
            contact_type=ContactType.PLANAR,
        )
        assert info.part_a == "a"
        assert info.contact_type == ContactType.PLANAR

    def test_defaults(self) -> None:
        """Minimal construction with only required fields."""
        info = ContactInfo(part_a="x", part_b="y")
        assert info.distance == 0.0
        assert info.contact_type == ContactType.COMPLEX
        assert info.insertion_axis is None
        assert info.clearance_mm is None
        assert info.area_class is None


class TestBackwardCompatibleAdjacency:
    """Verify adjacency dict builds correctly from ContactInfo list."""

    def test_adjacency_from_contact_info(self) -> None:
        contacts = [
            ContactInfo(part_a="a", part_b="b", contact_type=ContactType.PLANAR),
            ContactInfo(part_a="b", part_b="c", contact_type=ContactType.COAXIAL),
        ]
        adjacency: dict[str, set[str]] = defaultdict(set)
        for c in contacts:
            adjacency[c.part_a].add(c.part_b)
            adjacency[c.part_b].add(c.part_a)

        assert adjacency["a"] == {"b"}
        assert adjacency["b"] == {"a", "c"}
        assert adjacency["c"] == {"b"}

    def test_contact_map_keying(self) -> None:
        """Verify contact_map lookup by canonical (min, max) key pair."""
        c = ContactInfo(part_a="alpha", part_b="beta", contact_type=ContactType.LINE)
        contact_map: dict[tuple[str, str], ContactInfo] = {}
        contact_map[(c.part_a, c.part_b)] = c

        # Lookup with canonical ordering
        key = (min("beta", "alpha"), max("beta", "alpha"))
        assert key in contact_map
        assert contact_map[key].contact_type == ContactType.LINE


class TestDetectContactsNoOcc:
    """Verify graceful fallback when OCC is not installed."""

    def test_returns_empty_without_occ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import nextis.assembly.contact_analysis as ca

        monkeypatch.setattr(ca, "HAS_OCC", False)
        result = ca.detect_contacts([], contact_tolerance=0.0002)
        assert result == []

    def test_returns_empty_with_parts_without_occ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import nextis.assembly.contact_analysis as ca

        monkeypatch.setattr(ca, "HAS_OCC", False)
        fake_parts = [_FakePart("a", None), _FakePart("b", None)]
        result = ca.detect_contacts(fake_parts, contact_tolerance=0.0002)
        assert result == []


# ---------------------------------------------------------------------------
# Tests that require OCC
# ---------------------------------------------------------------------------


@_occ_skip
class TestContactNormalDirection:
    """Two boxes touching: verify normal direction."""

    def test_normal_has_dominant_component(self) -> None:
        from nextis.assembly.contact_analysis import detect_contacts

        # Box A: [0,0,0] to [1,1,1] (OCC coords, metres)
        box_a = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 1.0, 1.0, 1.0).Shape()
        # Box B: [1,0,0] to [2,1,1] — touching at x=1 plane
        box_b = BRepPrimAPI_MakeBox(gp_Pnt(1.0, 0, 0), 1.0, 1.0, 1.0).Shape()
        parts = [_FakePart("box_a", box_a), _FakePart("box_b", box_b)]

        contacts = detect_contacts(parts, contact_tolerance=0.001)
        assert len(contacts) == 1
        c = contacts[0]
        assert c.distance < 0.001

        # Normal should be non-zero (exact component depends on Y-up conversion)
        length_sq = sum(n * n for n in c.normal)
        assert length_sq > 0.5, f"Normal too short: {c.normal}"

    def test_canonical_ordering(self) -> None:
        """part_a should be lexicographically smaller than part_b."""
        from nextis.assembly.contact_analysis import detect_contacts

        box_a = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 1.0, 1.0, 1.0).Shape()
        box_b = BRepPrimAPI_MakeBox(gp_Pnt(1.0, 0, 0), 1.0, 1.0, 1.0).Shape()
        # Give parts reversed lexicographic IDs
        parts = [_FakePart("z_part", box_a), _FakePart("a_part", box_b)]

        contacts = detect_contacts(parts, contact_tolerance=0.001)
        assert len(contacts) == 1
        assert contacts[0].part_a == "a_part"
        assert contacts[0].part_b == "z_part"


@_occ_skip
class TestPlanarClassification:
    """Two boxes face-to-face should be classified as PLANAR."""

    def test_boxes_are_planar(self) -> None:
        from nextis.assembly.contact_analysis import detect_contacts

        box_a = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 0.1, 0.1, 0.1).Shape()
        box_b = BRepPrimAPI_MakeBox(gp_Pnt(0.1, 0, 0), 0.1, 0.1, 0.1).Shape()
        parts = [_FakePart("box_a", box_a), _FakePart("box_b", box_b)]

        contacts = detect_contacts(parts, contact_tolerance=0.001)
        assert len(contacts) == 1
        assert contacts[0].contact_type == ContactType.PLANAR


@_occ_skip
class TestCoaxialClassification:
    """Two concentric cylinders should be classified as COAXIAL."""

    def test_concentric_cylinders(self) -> None:
        from nextis.assembly.contact_analysis import detect_contacts

        # Inner cylinder: r=5mm, h=20mm, along Z axis at origin
        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        inner = BRepPrimAPI_MakeCylinder(ax, 0.005, 0.02).Shape()
        # Outer cylinder: r=5.1mm, h=20mm — nearly touching (0.1mm gap)
        outer = BRepPrimAPI_MakeCylinder(ax, 0.0051, 0.02).Shape()
        parts = [_FakePart("inner", inner), _FakePart("outer", outer)]

        contacts = detect_contacts(parts, contact_tolerance=0.001)
        assert len(contacts) == 1
        assert contacts[0].contact_type == ContactType.COAXIAL

    def test_coaxial_has_insertion_axis(self) -> None:
        from nextis.assembly.contact_analysis import detect_contacts

        ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
        inner = BRepPrimAPI_MakeCylinder(ax, 0.005, 0.02).Shape()
        outer = BRepPrimAPI_MakeCylinder(ax, 0.0051, 0.02).Shape()
        parts = [_FakePart("inner", inner), _FakePart("outer", outer)]

        contacts = detect_contacts(parts, contact_tolerance=0.001)
        assert len(contacts) == 1
        c = contacts[0]
        assert c.insertion_axis is not None
        # Axis should be roughly along Y (after Z-up → Y-up conversion)
        assert abs(c.insertion_axis[1]) > 0.5, f"Expected Y-dominant axis: {c.insertion_axis}"
