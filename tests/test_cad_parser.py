"""Tests for the CAD parser and sequence planner.

Requires OCP (pip: cadquery-ocp) or pythonocc-core (conda).
All tests are skipped automatically when neither is available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Guard: skip all tests if no OpenCASCADE bindings installed
_occ_available = True
try:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Writer as XDEWriter
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
except ImportError:
    try:
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
        from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
        from OCC.Core.IFSelect import IFSelect_RetDone
        from OCC.Core.STEPCAFControl import STEPCAFControl_Writer as XDEWriter
        from OCC.Core.STEPControl import STEPControl_AsIs, STEPControl_Writer
        from OCC.Core.TCollection import TCollection_ExtendedString
        from OCC.Core.TDataStd import TDataStd_Name
        from OCC.Core.TDocStd import TDocStd_Document
        from OCC.Core.TopLoc import TopLoc_Location
        from OCC.Core.XCAFApp import XCAFApp_Application
        from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
    except ImportError:
        _occ_available = False

pytestmark = pytest.mark.skipif(not _occ_available, reason="OCP/pythonocc-core not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def step_file_3parts(tmp_path: Path) -> Path:
    """Create a STEP file with a box + two cylinders.

    Layout (in metres):
    - Housing: 80x40x60mm box centred at origin
    - Bearing: cylinder r=15mm h=10mm, sitting on top of housing
    - Pin: small cylinder r=3mm h=15mm, inside the housing
    """
    writer = STEPControl_Writer()

    # Housing (box)
    housing = BRepPrimAPI_MakeBox(gp_Pnt(-0.04, 0, -0.03), 0.08, 0.04, 0.06).Shape()
    writer.Transfer(housing, STEPControl_AsIs)

    # Bearing (cylinder on top face of housing)
    ax_bearing = gp_Ax2(gp_Pnt(0, 0.04, 0), gp_Dir(0, 1, 0))
    bearing = BRepPrimAPI_MakeCylinder(ax_bearing, 0.015, 0.01).Shape()
    writer.Transfer(bearing, STEPControl_AsIs)

    # Pin (small cylinder)
    ax_pin = gp_Ax2(gp_Pnt(-0.025, 0.01, 0), gp_Dir(0, 1, 0))
    pin = BRepPrimAPI_MakeCylinder(ax_pin, 0.003, 0.015).Shape()
    writer.Transfer(pin, STEPControl_AsIs)

    step_path = tmp_path / "test_assembly.step"
    status = writer.Write(str(step_path))
    assert status == IFSelect_RetDone, "Failed to write test STEP file"
    return step_path


@pytest.fixture()
def step_file_single_box(tmp_path: Path) -> Path:
    """Create a STEP file with a single box (no assembly structure)."""
    writer = STEPControl_Writer()
    box = BRepPrimAPI_MakeBox(0.1, 0.05, 0.03).Shape()
    writer.Transfer(box, STEPControl_AsIs)
    path = tmp_path / "single_box.step"
    status = writer.Write(str(path))
    assert status == IFSelect_RetDone
    return path


def _get_static(cls, method: str):
    """Get a static method from an OCC class, trying OCP '_s' suffix first."""
    return getattr(cls, f"{method}_s", None) or getattr(cls, method)


@pytest.fixture()
def step_file_nested_hierarchy(tmp_path: Path) -> Path:
    """Create a STEP file with a 2-level assembly hierarchy via XDE.

    Structure:
        TopAssembly
          └─ SubAssembly @ translate(0.010, 0, 0)
               ├─ BoxA (1×1×1 mm) @ translate(0, 0.005, 0)
               └─ BoxB (2×2×2 mm) @ translate(0, 0, 0.003)

    Expected global centroids (in mm, before m-normalisation):
        BoxA: (10 + 0.5, 5 + 0.5, 0 + 0.5) = (10.5, 5.5, 0.5)
        BoxB: (10 + 1.0, 0 + 1.0, 3 + 1.0) = (11.0, 1.0, 4.0)
    """
    app = _get_static(XCAFApp_Application, "GetApplication")()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)

    shape_tool = _get_static(XCAFDoc_DocumentTool, "ShapeTool")(doc.Main())

    # Create definition shapes (at origin, no location).
    box_a = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    box_b = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()

    label_a = shape_tool.AddShape(box_a)
    label_b = shape_tool.AddShape(box_b)

    # Name the parts.
    TDataStd_Name.Set_s(label_a, TCollection_ExtendedString("BoxA"))
    TDataStd_Name.Set_s(label_b, TCollection_ExtendedString("BoxB"))

    # Create sub-assembly and add the two boxes as components with local offsets.
    sub_asm_label = shape_tool.NewShape()
    TDataStd_Name.Set_s(sub_asm_label, TCollection_ExtendedString("SubAssembly"))

    trsf_a = gp_Trsf()
    trsf_a.SetTranslation(gp_Vec(0.0, 5.0, 0.0))
    shape_tool.AddComponent(sub_asm_label, label_a, TopLoc_Location(trsf_a))

    trsf_b = gp_Trsf()
    trsf_b.SetTranslation(gp_Vec(0.0, 0.0, 3.0))
    shape_tool.AddComponent(sub_asm_label, label_b, TopLoc_Location(trsf_b))

    # Create top-level assembly with the sub-assembly offset by X=10.
    top_label = shape_tool.NewShape()
    TDataStd_Name.Set_s(top_label, TCollection_ExtendedString("TopAssembly"))

    trsf_sub = gp_Trsf()
    trsf_sub.SetTranslation(gp_Vec(10.0, 0.0, 0.0))
    shape_tool.AddComponent(top_label, sub_asm_label, TopLoc_Location(trsf_sub))

    shape_tool.UpdateAssemblies()

    # Write via XDE writer.
    writer = XDEWriter()
    writer.Transfer(doc, STEPControl_AsIs)
    step_path = tmp_path / "nested_hierarchy.step"
    status = writer.Write(str(step_path))
    assert status == IFSelect_RetDone, "Failed to write nested hierarchy STEP file"
    return step_path


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------
class TestCADParser:
    """Tests for CADParser.parse()."""

    def test_parse_extracts_correct_part_count(self, step_file_3parts: Path, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")
        assert len(result.graph.parts) == 3

    def test_parse_generates_glb_files(self, step_file_3parts: Path, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser

        mesh_dir = tmp_path / "meshes"
        parser = CADParser()
        parser.parse(step_file_3parts, mesh_dir)

        glb_files = list(mesh_dir.glob("*.glb"))
        assert len(glb_files) >= 1, f"Expected GLB files, found: {glb_files}"

    def test_parse_assigns_position_and_geometry(self, step_file_3parts: Path, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")

        for part in result.graph.parts.values():
            assert part.position is not None, f"{part.id} missing position"
            assert len(part.position) == 3
            assert part.geometry in {"box", "cylinder", "sphere"}, f"{part.id}: {part.geometry}"
            assert part.dimensions is not None and len(part.dimensions) >= 1
            assert part.color is not None and part.color.startswith("#")

    def test_parse_assigns_mesh_file_paths(self, step_file_3parts: Path, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")

        parts_with_mesh = [p for p in result.graph.parts.values() if p.mesh_file]
        assert len(parts_with_mesh) >= 1, "Expected at least one part with mesh_file"
        for part in parts_with_mesh:
            assert part.mesh_file.endswith(".glb")

    def test_parse_single_part(self, step_file_single_box: Path, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        result = parser.parse(step_file_single_box, tmp_path / "meshes")
        assert len(result.graph.parts) == 1
        assert result.contacts == []

    def test_parse_nonexistent_file_raises(self, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        with pytest.raises(FileNotFoundError):
            parser.parse(tmp_path / "no_such_file.step", tmp_path / "meshes")

    def test_parse_invalid_suffix_raises(self, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser
        from nextis.errors import CADParseError

        bad_file = tmp_path / "readme.txt"
        bad_file.write_text("not a step file")
        parser = CADParser()
        with pytest.raises(CADParseError, match="Expected .step/.stp"):
            parser.parse(bad_file, tmp_path / "meshes")

    def test_tessellate_returns_bbox_center(self, tmp_path: Path):
        """tessellate_to_glb returns (True, bbox_center) with correct center."""
        from nextis.assembly.mesh_utils import tessellate_to_glb

        # Box at offset position — bbox center should be near (12.5, 22.5, 32.5)
        box = BRepPrimAPI_MakeBox(gp_Pnt(10.0, 20.0, 30.0), 5.0, 5.0, 5.0).Shape()
        output = tmp_path / "test_bbox_center.glb"
        success, bbox_center = tessellate_to_glb(box, output)

        assert success is True
        assert len(bbox_center) == 3
        # After Z-up→Y-up conversion: [12.5, 22.5, 32.5] → [12.5, 32.5, -22.5]
        assert abs(bbox_center[0] - 12.5) < 0.5
        assert abs(bbox_center[1] - 32.5) < 0.5
        assert abs(bbox_center[2] - (-22.5)) < 0.5

    def test_bbox_center_vs_vertex_mean(self):
        """Bbox center is [0,0,0] for symmetric bounds, even with skewed density."""
        import numpy as np

        # 100 vertices clustered near [10,0,0], 10 near [-10,0,0]
        dense = np.random.default_rng(42).normal(loc=[10, 0, 0], scale=0.1, size=(100, 3))
        sparse = np.random.default_rng(42).normal(loc=[-10, 0, 0], scale=0.1, size=(10, 3))
        verts = np.vstack([dense, sparse])

        vertex_mean = verts.mean(axis=0)
        bbox_center = (verts.min(axis=0) + verts.max(axis=0)) / 2

        # Vertex mean is heavily skewed toward the dense cluster (~8.2)
        assert abs(vertex_mean[0]) > 5.0, "Mean should be skewed toward dense side"
        # Bbox center should be near 0 (geometric midpoint of extents)
        assert abs(bbox_center[0]) < 1.0, f"Bbox center X should be ~0, got {bbox_center[0]}"
        assert abs(bbox_center[1]) < 1.0
        assert abs(bbox_center[2]) < 1.0

    def test_tessellate_failure_returns_zero_centroid(self, tmp_path: Path):
        """Failed tessellation returns (False, [0, 0, 0])."""
        from nextis.assembly.mesh_utils import tessellate_to_glb

        try:
            from OCP.TopoDS import TopoDS_Shape
        except ImportError:
            from OCC.Core.TopoDS import TopoDS_Shape

        empty_shape = TopoDS_Shape()
        output = tmp_path / "empty.glb"
        success, centroid = tessellate_to_glb(empty_shape, output)

        assert success is False
        assert centroid == [0.0, 0.0, 0.0]

    def test_parse_positions_are_distinct(self, step_file_3parts: Path, tmp_path: Path):
        """All parts in a multi-part assembly must have distinct positions."""
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")

        positions = [tuple(p.position) for p in result.graph.parts.values()]
        assert len(set(positions)) == len(positions), f"Parts have duplicate positions: {positions}"

    def test_assembly_graph_round_trip(self, step_file_3parts: Path, tmp_path: Path):
        """Graph from parser survives JSON serialize/deserialize."""
        from nextis.assembly.cad_parser import CADParser
        from nextis.assembly.models import AssemblyGraph

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")
        graph = result.graph

        json_path = tmp_path / "test_graph.json"
        graph.to_json_file(json_path)
        loaded = AssemblyGraph.from_json_file(json_path)

        assert loaded.id == graph.id
        assert len(loaded.parts) == len(graph.parts)
        for part_id in graph.parts:
            assert part_id in loaded.parts

    # ------------------------------------------------------------------
    # Unit handling tests
    # ------------------------------------------------------------------
    def test_mm_input_produces_metre_positions(self, tmp_path: Path):
        """STEP file in mm (coords > 1.0) produces metre-scale Part positions."""
        from nextis.assembly.cad_parser import CADParser

        writer = STEPControl_Writer()
        # Box at (10, 20, 30) with size 50x50x50 — clearly in mm
        box = BRepPrimAPI_MakeBox(gp_Pnt(10.0, 20.0, 30.0), 50.0, 50.0, 50.0).Shape()
        writer.Transfer(box, STEPControl_AsIs)
        step_path = tmp_path / "mm_box.step"
        assert writer.Write(str(step_path)) == IFSelect_RetDone

        parser = CADParser()
        result = parser.parse(step_path, tmp_path / "meshes")

        assert result.units == "mm"
        assert result.unit_scale == pytest.approx(0.001)

        part = list(result.graph.parts.values())[0]
        # Bbox center of (10,20,30)+(50,50,50) box is (35,45,55) mm → (0.035,0.045,0.055) m
        assert all(abs(v) < 0.1 for v in part.position), (
            f"Expected metre-scale positions, got {part.position}"
        )
        assert part.dimensions is not None
        assert all(d < 0.1 for d in part.dimensions), (
            f"Expected metre-scale dimensions, got {part.dimensions}"
        )

    def test_metre_input_no_double_scaling(self, step_file_3parts: Path, tmp_path: Path):
        """STEP file already in metres (coords < 1.0) must not be scaled again."""
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")

        assert result.units == "m"
        assert result.unit_scale == pytest.approx(1.0)

        for part in result.graph.parts.values():
            assert all(abs(v) < 0.2 for v in part.position), (
                f"{part.id}: position out of range: {part.position}"
            )

    def test_glb_vertices_in_metres_after_scaling(self, tmp_path: Path):
        """tessellate_to_glb with unit_scale=0.001 produces metre-scale GLB."""
        import trimesh

        from nextis.assembly.mesh_utils import tessellate_to_glb

        # Box 50x50x50 at origin — in mm
        box = BRepPrimAPI_MakeBox(50.0, 50.0, 50.0).Shape()
        output = tmp_path / "scaled.glb"
        success, center = tessellate_to_glb(box, output, unit_scale=0.001)

        assert success
        # Bbox center (25,25,25) mm → Y-up (0.025,0.025,-0.025) m
        assert abs(center[0] - 0.025) < 0.005
        assert abs(center[1] - 0.025) < 0.005
        assert abs(center[2] - (-0.025)) < 0.005

        # Load GLB and verify vertex extents are metre-scale
        mesh = trimesh.load(str(output))
        extents = mesh.bounding_box.extents
        assert all(e < 0.1 for e in extents), (
            f"Expected metre-scale GLB extents, got {extents}"
        )

    def test_unit_scale_json_round_trip(self, step_file_3parts: Path, tmp_path: Path):
        """unitScale field round-trips through JSON serialization."""
        from nextis.assembly.cad_parser import CADParser
        from nextis.assembly.models import AssemblyGraph

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")
        graph = result.graph

        json_path = tmp_path / "unit_scale_rt.json"
        graph.to_json_file(json_path)
        loaded = AssemblyGraph.from_json_file(json_path)

        assert loaded.unit_scale == graph.unit_scale

    def test_nested_hierarchy_correct_positions(
        self, step_file_nested_hierarchy: Path, tmp_path: Path
    ):
        """Parts in nested sub-assemblies get composed global transforms.

        SubAssembly is placed at X=10, BoxA at Y=5, BoxB at Z=3.
        OCC Z-up centroids:
            BoxA: (10.5, 5.5, 0.5)
            BoxB: (11.0, 1.0, 4.0)
        After Z-up→Y-up conversion [x,y,z]→[x,z,-y] and mm→m:
            BoxA: (0.0105, 0.0005, -0.0055)
            BoxB: (0.011, 0.004, -0.001)
        """
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        result = parser.parse(step_file_nested_hierarchy, tmp_path / "meshes")

        # Should find 2 separate parts, not 1 merged compound.
        assert len(result.graph.parts) == 2

        # Collect positions (already normalised to metres by the parser).
        positions = sorted(
            [p.position for p in result.graph.parts.values()],
            key=lambda p: (p[0], p[1]),
        )

        # BoxA: Y-up (0.0105, 0.0005, -0.0055) m
        assert abs(positions[0][0] - 0.0105) < 0.001
        assert abs(positions[0][1] - 0.0005) < 0.001
        assert abs(positions[0][2] - (-0.0055)) < 0.001

        # BoxB: Y-up (0.011, 0.004, -0.001) m
        assert abs(positions[1][0] - 0.011) < 0.001
        assert abs(positions[1][1] - 0.004) < 0.001
        assert abs(positions[1][2] - (-0.001)) < 0.001

    def test_nested_hierarchy_positions_are_distinct(
        self, step_file_nested_hierarchy: Path, tmp_path: Path
    ):
        """Parts from nested hierarchy must not share positions."""
        from nextis.assembly.cad_parser import CADParser

        parser = CADParser()
        result = parser.parse(step_file_nested_hierarchy, tmp_path / "meshes")

        positions = [tuple(p.position) for p in result.graph.parts.values()]
        assert len(set(positions)) == len(positions), (
            f"Parts have duplicate positions: {positions}"
        )


# ---------------------------------------------------------------------------
# Geometry classification tests
# ---------------------------------------------------------------------------
class TestClassifyGeometry:
    """Tests for the classify_geometry helper."""

    def test_box(self):
        from nextis.assembly.mesh_utils import classify_geometry

        geo, dims = classify_geometry(0.08, 0.04, 0.06)
        assert geo == "box"
        assert dims == [0.08, 0.04, 0.06]

    def test_cylinder(self):
        from nextis.assembly.mesh_utils import classify_geometry

        geo, _dims = classify_geometry(0.03, 0.1, 0.03)
        assert geo == "cylinder"

    def test_sphere(self):
        from nextis.assembly.mesh_utils import classify_geometry

        geo, _dims = classify_geometry(0.05, 0.05, 0.048)
        assert geo == "sphere"

    def test_flat_box(self):
        from nextis.assembly.mesh_utils import classify_geometry

        geo, dims = classify_geometry(0.1, 0.01, 0.1)
        assert geo == "box"
        assert len(dims) == 3


# ---------------------------------------------------------------------------
# Sequence planner tests
# ---------------------------------------------------------------------------
class TestSequencePlanner:
    """Tests for SequencePlanner.plan()."""

    def test_generates_steps(self, step_file_3parts: Path, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser
        from nextis.assembly.sequence_planner import SequencePlanner

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")

        planner = SequencePlanner()
        graph = planner.plan(result)

        assert len(graph.steps) > 0
        assert len(graph.step_order) == len(graph.steps)

    def test_step_order_ids_exist_in_steps(self, step_file_3parts: Path, tmp_path: Path):
        from nextis.assembly.cad_parser import CADParser
        from nextis.assembly.sequence_planner import SequencePlanner

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")
        graph = SequencePlanner().plan(result)

        for step_id in graph.step_order:
            assert step_id in graph.steps, f"{step_id} not in steps dict"

    def test_dependencies_respected(self, step_file_3parts: Path, tmp_path: Path):
        """All dependencies appear before their dependent step in step_order."""
        from nextis.assembly.cad_parser import CADParser
        from nextis.assembly.sequence_planner import SequencePlanner

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")
        graph = SequencePlanner().plan(result)

        order_index = {sid: i for i, sid in enumerate(graph.step_order)}
        for step_id, step in graph.steps.items():
            for dep in step.dependencies:
                assert order_index[dep] < order_index[step_id], (
                    f"Dependency {dep} should come before {step_id}"
                )

    def test_empty_parts_raises(self):
        from nextis.assembly.cad_parser import ParseResult
        from nextis.assembly.models import AssemblyGraph
        from nextis.assembly.sequence_planner import SequencePlanner
        from nextis.errors import AssemblyError

        empty = ParseResult(
            graph=AssemblyGraph(id="empty", name="Empty"),
            contacts=[],
        )
        with pytest.raises(AssemblyError, match="no parts"):
            SequencePlanner().plan(empty)

    def test_full_pipeline_round_trip(self, step_file_3parts: Path, tmp_path: Path):
        """Full pipeline: parse → plan → serialize → deserialize."""
        from nextis.assembly.cad_parser import CADParser
        from nextis.assembly.models import AssemblyGraph
        from nextis.assembly.sequence_planner import SequencePlanner

        parser = CADParser()
        result = parser.parse(step_file_3parts, tmp_path / "meshes")
        graph = SequencePlanner().plan(result)

        json_path = tmp_path / "full_pipeline.json"
        graph.to_json_file(json_path)
        loaded = AssemblyGraph.from_json_file(json_path)

        assert loaded.id == graph.id
        assert len(loaded.steps) == len(graph.steps)
        assert loaded.step_order == graph.step_order
