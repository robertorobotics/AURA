"""CAD parser: STEP files → AssemblyGraph + GLB meshes.

Reads STEP assembly files using OpenCASCADE (via OCP or pythonocc-core),
extracts part hierarchy with transforms, and detects inter-part contacts.
Mesh tessellation and geometry helpers live in mesh_utils.py.

Install one of:
    pip install cadquery-ocp-novtk    (recommended, fast)
    conda install -c conda-forge pythonocc-core   (slower)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nextis.assembly.mesh_utils import (
    classify_geometry,
    color_for_part,
    compute_bounding_box,
    tessellate_to_glb,
    trsf_to_pos_rot,
)
from nextis.assembly.models import AssemblyGraph, Part
from nextis.errors import CADParseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional OCC imports — try OCP (pip) first, then OCC.Core (conda)
# ---------------------------------------------------------------------------
try:
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    HAS_OCC = True
except ImportError:
    try:
        from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
        from OCC.Core.IFSelect import IFSelect_RetDone
        from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.TCollection import TCollection_ExtendedString
        from OCC.Core.TDataStd import TDataStd_Name
        from OCC.Core.TDF import TDF_Label, TDF_LabelSequence
        from OCC.Core.TDocStd import TDocStd_Document
        from OCC.Core.TopAbs import TopAbs_SOLID
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.XCAFApp import XCAFApp_Application
        from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool

        XCAFDoc_ShapeTool = None  # pythonocc uses instance methods
        HAS_OCC = True
    except ImportError:
        HAS_OCC = False
        XCAFDoc_ShapeTool = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_VALID_SUFFIXES = {".step", ".stp"}


def _static(cls: Any, method: str) -> Any:
    """Get a static method from an OCC class, trying OCP '_s' suffix first."""
    return getattr(cls, f"{method}_s", None) or getattr(cls, method)


def _st_call(shape_tool: Any, method: str, *args: Any) -> Any:
    """Call a shape_tool method — instance in pythonocc, static in OCP."""
    fn = getattr(shape_tool, method, None)
    if fn is not None:
        return fn(*args)
    # OCP: static methods with _s suffix on the class
    return _static(type(shape_tool), method)(*args)


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------
@dataclass
class _RawPart:
    """Intermediate parsed part before conversion to the Part model."""

    name: str
    shape: Any  # TopoDS_Shape
    part_id: str = ""
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])


@dataclass
class ParseResult:
    """Output from CADParser.parse().

    Attributes:
        graph: Assembly graph with parts populated (steps empty).
        contacts: Pairs of part IDs detected to be in contact.
    """

    graph: AssemblyGraph
    contacts: list[tuple[str, str]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sanitize_id(name: str, index: int, seen: set[str]) -> str:
    """Create a clean, unique part ID from a label name.

    Args:
        name: Raw part name from the STEP file.
        index: Part index for disambiguation.
        seen: Set of already-used IDs (mutated in-place).

    Returns:
        Unique snake_case part ID.
    """
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not base:
        base = f"part_{index:03d}"
    candidate = base
    counter = 1
    while candidate in seen:
        counter += 1
        candidate = f"{base}_{counter}"
    seen.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# CADParser
# ---------------------------------------------------------------------------
class CADParser:
    """Parse STEP assembly files into AssemblyGraph structures.

    Uses PythonOCC XDE reader to extract part hierarchy, transforms, and
    geometry. Falls back to flat shape extraction if the STEP file lacks
    assembly structure.

    Args:
        linear_deflection: Tessellation mesh density (metres). Lower = finer.
        contact_tolerance: Max distance (metres) to consider parts in contact.
    """

    def __init__(
        self,
        linear_deflection: float = 0.001,
        contact_tolerance: float = 0.0002,
    ) -> None:
        if not HAS_OCC:
            raise CADParseError(
                "pythonocc-core is required for CAD parsing. "
                "Install via: conda install -c conda-forge pythonocc-core"
            )
        self._linear_deflection = linear_deflection
        self._contact_tolerance = contact_tolerance

    def parse(
        self,
        step_file: Path,
        output_dir: Path,
        assembly_name: str | None = None,
    ) -> ParseResult:
        """Parse a STEP file into an AssemblyGraph with GLB meshes.

        Args:
            step_file: Path to the .step/.stp file.
            output_dir: Directory to write GLB mesh files.
            assembly_name: Human-readable name. Defaults to filename stem.

        Returns:
            ParseResult with the graph (parts populated, steps empty) and
            contact pairs.

        Raises:
            CADParseError: If the file cannot be parsed or contains no geometry.
            FileNotFoundError: If step_file does not exist.
        """
        step_file = Path(step_file)
        if not step_file.exists():
            raise FileNotFoundError(f"STEP file not found: {step_file}")
        if step_file.suffix.lower() not in _VALID_SUFFIXES:
            raise CADParseError(f"Expected .step/.stp file, got {step_file.suffix}")

        logger.info("Parsing STEP file: %s", step_file)

        # Try XDE first, fall back to flat
        raw_parts = self._extract_parts_xde(step_file)
        if not raw_parts:
            logger.info("XDE yielded 0 parts, falling back to flat reader")
            raw_parts = self._extract_parts_flat(step_file)
        if not raw_parts:
            raise CADParseError(f"No geometry found in {step_file.name}")

        logger.info("Extracted %d part(s) from %s", len(raw_parts), step_file.name)

        # Assign unique IDs
        seen_ids: set[str] = set()
        for i, rp in enumerate(raw_parts):
            rp.part_id = _sanitize_id(rp.name, i, seen_ids)

        # Build output directory
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Derive assembly ID and name
        assembly_id = re.sub(r"[^a-z0-9]+", "_", step_file.stem.lower()).strip("_")
        name = assembly_name or step_file.stem

        # Process each part
        parts: dict[str, Part] = {}
        for i, rp in enumerate(raw_parts):
            part = self._process_part(rp, i, assembly_id, output_dir)
            parts[part.id] = part

        # Detect contacts
        contacts = self._detect_contacts(raw_parts)

        graph = AssemblyGraph(id=assembly_id, name=name, parts=parts)
        logger.info(
            "Built assembly graph '%s': %d parts, %d contacts",
            assembly_id,
            len(parts),
            len(contacts),
        )
        return ParseResult(graph=graph, contacts=contacts)

    # ------------------------------------------------------------------
    # XDE reader (preserves assembly hierarchy and part names)
    # ------------------------------------------------------------------
    def _extract_parts_xde(self, step_file: Path) -> list[_RawPart]:
        """Read STEP via XDE and walk the label tree for named parts."""
        try:
            app = _static(XCAFApp_Application, "GetApplication")()
            doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
            app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)

            reader = STEPCAFControl_Reader()
            reader.SetNameMode(True)
            status = reader.ReadFile(str(step_file))
            if status != IFSelect_RetDone:
                logger.warning("XDE reader failed for %s", step_file.name)
                return []

            if not reader.Transfer(doc):
                logger.warning("XDE transfer failed for %s", step_file.name)
                return []

            shape_tool = _static(XCAFDoc_DocumentTool, "ShapeTool")(doc.Main())
            labels = TDF_LabelSequence()
            shape_tool.GetFreeShapes(labels)

            raw_parts: list[_RawPart] = []
            for i in range(labels.Length()):
                label = labels.Value(i + 1)
                self._walk_label(shape_tool, label, raw_parts)

            return raw_parts
        except Exception as exc:
            logger.warning("XDE extraction error: %s", exc)
            return []

    def _walk_label(
        self,
        shape_tool: Any,
        label: Any,
        out: list[_RawPart],
    ) -> None:
        """Recursively walk a TDF_Label tree, collecting leaf shapes."""
        if _st_call(shape_tool, "IsAssembly", label):
            components = TDF_LabelSequence()
            _st_call(shape_tool, "GetComponents", label, components)
            for i in range(components.Length()):
                self._walk_label(shape_tool, components.Value(i + 1), out)
            return

        # Resolve references
        ref_label = TDF_Label()
        actual_label = (
            ref_label
            if _st_call(shape_tool, "GetReferredShape", label, ref_label)
            else label
        )

        shape = _st_call(shape_tool, "GetShape", actual_label)
        if shape is None or shape.IsNull():
            return

        name = self._get_label_name(actual_label) or f"Part_{len(out) + 1}"

        # Get transform from the original (possibly reference) label
        loc_shape = _st_call(shape_tool, "GetShape", label)
        trsf = loc_shape.Location().Transformation()
        try:
            pos, rot = trsf_to_pos_rot(trsf)
        except Exception:
            pos, rot = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]

        out.append(_RawPart(name=name, shape=shape, position=pos, rotation=rot))

    @staticmethod
    def _get_label_name(label: Any) -> str | None:
        """Extract a human-readable name from a TDF_Label."""
        try:
            name_attr = TDataStd_Name()
            if label.FindAttribute(_static(TDataStd_Name, "GetID")(), name_attr):
                return name_attr.Get().ToExtString()
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Flat reader (fallback for non-assembly STEP files)
    # ------------------------------------------------------------------
    def _extract_parts_flat(self, step_file: Path) -> list[_RawPart]:
        """Read STEP via flat reader and extract individual solids."""
        try:
            reader = STEPControl_Reader()
            status = reader.ReadFile(str(step_file))
            if status != IFSelect_RetDone:
                raise CADParseError(f"STEP reader failed for {step_file.name}")

            reader.TransferRoots()
            shape = reader.OneShape()
            if shape is None or shape.IsNull():
                return []

            raw_parts: list[_RawPart] = []
            explorer = TopExp_Explorer(shape, TopAbs_SOLID)
            idx = 0
            while explorer.More():
                solid = explorer.Current()
                idx += 1
                rp = _RawPart(name=f"Part_{idx}", shape=solid)
                try:
                    center, _, _ = compute_bounding_box(solid)
                    rp.position = center
                except Exception:
                    pass
                raw_parts.append(rp)
                explorer.Next()

            return raw_parts
        except CADParseError:
            raise
        except Exception as exc:
            logger.warning("Flat extraction error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Part processing
    # ------------------------------------------------------------------
    def _process_part(
        self,
        rp: _RawPart,
        index: int,
        assembly_id: str,
        output_dir: Path,
    ) -> Part:
        """Convert a _RawPart into a Part model with mesh and geometry."""
        try:
            center, extents, _ = compute_bounding_box(rp.shape)
        except Exception as exc:
            logger.warning("Bounding box failed for %s: %s", rp.part_id, exc)
            center = [0.0, 0.0, 0.0]
            extents = [0.05, 0.05, 0.05]

        # Prefer transform position; fall back to bbox center
        pos = rp.position if any(abs(v) > 1e-9 for v in rp.position) else center

        geo_type, dims = classify_geometry(extents[0], extents[1], extents[2])
        color = color_for_part(rp.name, index)

        # Tessellate to GLB
        mesh_path = output_dir / f"{rp.part_id}.glb"
        mesh_file: str | None = None
        if tessellate_to_glb(rp.shape, mesh_path, self._linear_deflection):
            mesh_file = f"/meshes/{assembly_id}/{rp.part_id}.glb"

        return Part(
            id=rp.part_id,
            cad_file=None,
            mesh_file=mesh_file,
            position=pos,
            rotation=rp.rotation,
            geometry=geo_type,
            dimensions=dims,
            color=color,
        )

    # ------------------------------------------------------------------
    # Contact detection
    # ------------------------------------------------------------------
    def _detect_contacts(self, parts: list[_RawPart]) -> list[tuple[str, str]]:
        """Find pairs of parts in contact (distance < tolerance).

        O(n^2) but assemblies are small (typically 2-50 parts).
        """
        contacts: list[tuple[str, str]] = []
        n = len(parts)
        for i in range(n):
            for j in range(i + 1, n):
                try:
                    dist_tool = BRepExtrema_DistShapeShape(
                        parts[i].shape,
                        parts[j].shape,
                    )
                    if dist_tool.IsDone() and dist_tool.Value() < self._contact_tolerance:
                        contacts.append((parts[i].part_id, parts[j].part_id))
                        logger.debug(
                            "Contact: %s ↔ %s (dist=%.6f)",
                            parts[i].part_id,
                            parts[j].part_id,
                            dist_tool.Value(),
                        )
                except Exception as exc:
                    logger.debug(
                        "Contact check failed for %s/%s: %s",
                        parts[i].part_id,
                        parts[j].part_id,
                        exc,
                    )
        logger.info("Detected %d contact pair(s) among %d parts", len(contacts), n)
        return contacts
