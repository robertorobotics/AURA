# CLAUDE.md — Nextis Universal Assembler v2

## Project Identity

**Nextis** is building universal constructor technology — robots that can autonomously assemble anything, including parts of themselves. This repo (`nextis-assembler`) is the v2 rebuild: a CAD-driven assembly automation platform built on top of a proven teleoperation and robot learning stack.

**Founder:** Roberto De la Cruz. Physics BSc, paused Master's in Robotics at TUM. Working from Hamburg, building toward YC S25.

**North star:** Upload a STEP file → system plans the assembly → robot builds it autonomously. Setup time < 2 days per new product.

**Philosophical lineage:** Von Neumann's universal constructor theory → Turing's computational foundations → David Deutsch's constructor theory. Just as PCs fulfilled Turing's vision, constructors will fulfill von Neumann's dream.

---

## Architecture Overview

```
nextis-assembler/
├── lerobot/                        # Git submodule (Nextis fork of LeRobot)
├── nextis/
│   ├── hardware/                   # Motor control & arm management
│   ├── control/                    # Real-time 60Hz control loop
│   ├── assembly/                   # CAD parsing, assembly graphs, planning
│   ├── execution/                  # Task sequencer, primitives, error recovery
│   ├── perception/                 # Step completion, force interpretation
│   ├── learning/                   # Per-step training, RL, data collection
│   ├── analytics/                  # Metrics, cycle time, dashboard data
│   └── api/                        # Thin FastAPI layer
├── frontend/                       # Minimal Next.js (assembly dashboard)
├── configs/                        # Hardware & assembly YAML configs
├── scripts/                        # Setup & calibration scripts
└── tests/
```

### Central Data Model: The Assembly Graph

**Everything is indexed by the assembly graph.** This is the spine of the entire system.

```python
# nextis/assembly/models.py
@dataclass
class AssemblyStep:
    id: str                          # e.g. "step_001"
    name: str                        # e.g. "Insert bearing into housing"
    part_ids: list[str]              # Parts involved
    dependencies: list[str]          # Step IDs that must complete first
    handler: str                     # "primitive" or "policy"
    primitive_type: str | None       # "pick", "place", "guarded_insert", etc.
    primitive_params: dict | None    # target_pose, force_threshold, etc.
    policy_id: str | None            # Trained policy checkpoint path
    success_criteria: dict           # How to verify completion
    max_retries: int = 3
    
@dataclass
class AssemblyGraph:
    id: str
    name: str
    parts: dict[str, Part]           # Part catalog with geometry
    steps: dict[str, AssemblyStep]   # Step definitions
    step_order: list[str]            # Topologically sorted execution order
```

Recording is per-step. Training is per-step. Execution walks the graph. Analytics are per-step. If you're writing code that doesn't reference a `step_id`, ask yourself why.

### Layer Responsibilities

| Layer | Does | Does NOT |
|-------|------|----------|
| `hardware/` | Motor drivers, arm registry, calibration, CAN bus | Know about assemblies, policies, or steps |
| `control/` | 60Hz teleop loop, force feedback, joint mapping, safety, primitives | Know about ML, datasets, or the frontend |
| `assembly/` | CAD parsing, assembly graph CRUD, sequence planning, grasp planning | Execute anything on hardware |
| `execution/` | Walk the assembly graph, dispatch primitives/policies, handle errors | Train policies or record data |
| `perception/` | Step completion detection, force interpretation | Control motors or plan sequences |
| `learning/` | Record step demos, train per-step policies, HIL-SERL | Execute assemblies or manage hardware |
| `analytics/` | Compute metrics, serve dashboard data | Make decisions about execution |
| `api/` | HTTP/WebSocket interface, request validation | Contain business logic |

**No layer reaches down more than one level.** `execution/` uses `control/` and `perception/`. It does NOT directly call `hardware/`. `control/` uses `hardware/`. `learning/` uses `control/` for recording.

---

## Engineering Standards

### Code Style

**Language:** Python 3.11+. Type hints on ALL function signatures. No `Any` unless genuinely unavoidable.

```python
# YES
def execute_step(self, step_id: str, timeout: float = 30.0) -> StepResult:

# NO
def execute_step(self, step_id, timeout=30.0):
```

**Formatting:** `ruff` for linting and formatting. Line length 100. Double quotes. Trailing commas in multi-line collections.

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.format]
quote-style = "double"
```

**Imports:** stdlib → third-party → lerobot → nextis. Absolute imports only within `nextis/`. No star imports ever.

```python
import time
import threading
from pathlib import Path

import numpy as np
import torch

from lerobot.motors.damiao.damiao import DamiaoMotorsBus
from lerobot.utils.robot_utils import precise_sleep

from nextis.hardware.types import ArmDefinition, MotorType
from nextis.control.safety import SafetyLayer
```

**Naming:**
- Classes: `PascalCase` — `AssemblyGraph`, `TeleopLoop`, `StepClassifier`
- Functions/methods: `snake_case` — `execute_step()`, `get_torque_limits()`
- Constants: `UPPER_SNAKE` — `MAX_VELOCITY`, `DEFAULT_KP`
- Private: single underscore prefix — `_compute_blend()`, `self._is_running`
- Files: `snake_case.py` — `teleop_loop.py`, `cad_parser.py`

**Docstrings:** Google style. Required on all public classes and functions. Keep them short and useful — what it does, not how it works internally.

```python
def train_step_policy(
    self,
    step_id: str,
    dataset_path: Path,
    architecture: str = "act",
    num_steps: int = 10_000,
) -> PolicyCheckpoint:
    """Train a policy for a single assembly step.

    Args:
        step_id: Assembly step to train for.
        dataset_path: Path to step-segmented dataset.
        architecture: Policy type — "act", "diffusion", or "smolvla".
        num_steps: Training iterations.

    Returns:
        Checkpoint with path, final loss, and step metadata.

    Raises:
        DatasetError: If dataset has no demos for this step.
    """
```

### Error Handling

**Use custom exceptions.** Never catch bare `Exception` in production code (only in top-level safety handlers).

```python
# nextis/errors.py
class NextisError(Exception):
    """Base exception for all Nextis errors."""

class HardwareError(NextisError):
    """Motor communication, CAN bus, or sensor failure."""

class CalibrationError(NextisError):
    """Arm not calibrated or calibration invalid."""

class AssemblyError(NextisError):
    """Assembly graph invalid or execution failure."""

class SafetyError(NextisError):
    """Safety limit exceeded — motors will be disabled."""
```

**Safety-critical code gets special treatment:**

```python
# In the 60Hz control loop — NEVER let an exception kill the loop
try:
    self._send_follower_command(action)
except HardwareError as e:
    logger.error(f"Follower command failed: {e}")
    self._consecutive_errors += 1
    if self._consecutive_errors > 10:
        self._emergency_stop()
        raise SafetyError("Too many consecutive hardware errors") from e
except Exception as e:
    # Last resort — log and continue to keep loop alive
    logger.critical(f"Unexpected error in control loop: {e}", exc_info=True)
```

### Logging

**Use `logging`, never `print()`.** The old codebase has hundreds of print statements. Do not replicate this.

```python
import logging
logger = logging.getLogger(__name__)

# Levels:
# DEBUG   — motor positions, frame counts, timing details (only in development)
# INFO    — state transitions, step completion, session start/stop
# WARNING — recoverable issues, retries, fallbacks
# ERROR   — failures that affect functionality
# CRITICAL — safety violations, emergency stops

logger.info("Assembly execution started: %s (%d steps)", assembly.name, len(assembly.steps))
logger.warning("Step %s failed (attempt %d/%d), retrying", step_id, attempt, max_retries)
logger.error("Force threshold exceeded on step %s: %.2f Nm > %.2f Nm", step_id, force, limit)
```

**Rate-limit repetitive logs in loops:**

```python
if self._loop_count % 60 == 0:  # Once per second at 60Hz
    logger.debug("Control loop: pos=%.3f, vel=%.3f, torque=%.2f", pos, vel, torque)
```

### Testing

**Test real behavior, not implementation details.** Focus on:
- Assembly graph validation (cycles, missing dependencies, invalid step configs)
- Sequencer state machine transitions
- Primitive parameter validation
- Step completion classifier accuracy
- Joint mapping correctness across motor types

```python
# tests/test_sequencer.py
def test_sequencer_advances_on_step_success():
    graph = make_test_assembly(steps=3)
    seq = Sequencer(graph)
    seq.start()
    assert seq.current_step_id == "step_001"
    
    seq.report_step_result(StepResult.SUCCESS)
    assert seq.current_step_id == "step_002"

def test_sequencer_retries_on_failure():
    graph = make_test_assembly(steps=3, max_retries=2)
    seq = Sequencer(graph)
    seq.start()
    
    seq.report_step_result(StepResult.FAILURE)
    assert seq.current_step_id == "step_001"  # Still on same step
    assert seq.attempt == 2

def test_sequencer_escalates_after_max_retries():
    graph = make_test_assembly(steps=3, max_retries=2)
    seq = Sequencer(graph)
    seq.start()
    
    seq.report_step_result(StepResult.FAILURE)  # attempt 2
    seq.report_step_result(StepResult.FAILURE)  # attempt 3 — exhausted
    assert seq.state == SequencerState.WAITING_FOR_HUMAN
```

### File Size Limits

**No file exceeds 500 lines.** If it's getting bigger, split it. The old `teleop_service.py` was 2154 lines because it mixed control, recording, and UI data. Don't repeat this.

Rough guidelines:
- Data models / types: < 150 lines
- Service classes: < 400 lines  
- Utility modules: < 200 lines
- API route files: < 200 lines
- Test files: < 300 lines

### Dependencies

**Minimize.** Every dependency is a liability on a robotics system.

Core (non-negotiable):
- `numpy` — math
- `torch` — ML
- `fastapi` + `uvicorn` — API
- `pyyaml` — config
- `lerobot` — robot framework (submodule)

Assembly layer:
- `pythonocc-core` (via conda) — STEP/IGES parsing. Heavy but no alternative.
- `trimesh` — mesh processing for 3D viewer export

Frontend:
- `next` — React framework
- `three` / `@react-three/fiber` — 3D viewer
- `recharts` — graphs
- `tailwindcss` — styling

**Do NOT add:** Flask, Django, SQLAlchemy, Celery, Redis, Docker (not yet), Kubernetes, any CSS framework beyond Tailwind, any state management beyond React state, any ORM.

---

## Agent Behavior Rules

### Planning & Progress Display

**When working on a multi-step task, only show the CURRENT problem.** Do not recap solved steps. Do not list all remaining steps. Show what you're doing RIGHT NOW and why.

```
# BAD — wastes context, loses focus
"I've completed steps 1-4. Now working on step 5. Steps 6-8 remain."

# GOOD — focused on the problem at hand
"Extracting the force feedback logic from teleop_service.py. 
The gripper EMA filter (lines 1328-1376) needs the follower torque 
reading decoupled from the active_robot reference."
```

### Decision Making

When facing a technical decision:

1. **State the constraint** — what does the system need?
2. **Pick the simplest solution that works** — not the most elegant, not the most scalable
3. **Implement it** — don't deliberate endlessly
4. **Document the trade-off** — one line comment explaining what was sacrificed

```python
# Using per-step classifiers instead of a unified scene model.
# Trade-off: can't generalize across unseen steps, but trains in minutes
# instead of hours and is debuggable per-step.
```

### When Stuck

If something isn't working after 2 attempts:
1. **Check the LeRobot source** — many issues come from API changes in the framework
2. **Check the old Nextis_Bridge code** — it likely solved this problem already
3. **Simplify** — remove the feature, use a hardcoded value, skip the optimization
4. **Ask** — don't spin for hours on something Roberto can answer in 30 seconds

### What NOT to Build

Do not build any of the following unless Roberto explicitly asks:
- Simulation environments (MuJoCo, PyBullet, Isaac)
- Natural language task specification
- Multi-robot coordination
- Cloud training pipelines
- CI/CD pipelines
- Docker containers
- Database backends (use filesystem + YAML + HDF5)
- Authentication / user management
- Elaborate admin dashboards
- Automated testing in CI (tests are run locally for now)

---

## Hardware Context

### Current Setup

**Follower arms (do the work):**
- Damiao Aira Zero — J8009P (shoulder), J4340P (elbow), J4310 (wrist), 7 DOF
- Connected via CAN bus (SocketCAN `can0` or serial bridge)
- MIT impedance control: J8009P kp=30 kd=1.5, J4340P kp=30 kd=1.5, J4310 kp=15 kd=0.25

**Leader arms (human operates):**
- Dynamixel XL330-M077/M288, USB serial
- Force feedback: gripper torque → Goal_Current ceiling, joint error → CURRENT_POSITION mode

**Cameras:**
- Intel RealSense — RGB + depth
- OpenCV webcams — RGB only

### Motor Communication

**Damiao (CAN):** Each motor command is a CAN frame. Round-trip ~2ms per motor. 7 motors = ~14ms for a full read. This is why the old code skips follower reads when not recording.

**Dynamixel (USB serial):** Packet-based protocol. Occasional "Incorrect status packet" errors — always retry up to 3 times with 5ms backoff.

**Critical timing:** The control loop runs at 60Hz (16.67ms per iteration). Camera capture is async (ZOH pattern). Recording runs at 30fps on a separate thread. Never block the control loop for I/O.

### Calibration

Each arm has a calibration profile stored in `configs/calibration/{arm_id}/`:
- `zeros.json` — encoder zero positions (homing)
- `ranges.json` — min/max per joint (range discovery)  
- `inversions.json` — motor direction corrections
- `gravity.json` — gravity compensation weights (linear regression)

Calibration must be run before first use and after any mechanical changes.

---

## Assembly System Design

### The Assembly Graph

An assembly graph is a JSON file in `configs/assemblies/`:

```json
{
  "id": "bearing_housing_v1",
  "name": "Bearing Housing Assembly",
  "parts": {
    "housing": {
      "cad_file": "housing.step",
      "mesh_file": "housing.glb",
      "grasp_points": [{"pose": [...], "approach": [...]}]
    },
    "bearing": {
      "cad_file": "bearing.step",
      "mesh_file": "bearing.glb",
      "grasp_points": [{"pose": [...], "approach": [...]}]
    }
  },
  "steps": {
    "step_001": {
      "name": "Pick housing",
      "part_ids": ["housing"],
      "dependencies": [],
      "handler": "primitive",
      "primitive_type": "pick",
      "primitive_params": {"part_id": "housing", "grasp_index": 0},
      "success_criteria": {"type": "force_threshold", "threshold": 0.5}
    },
    "step_002": {
      "name": "Place housing in fixture",
      "part_ids": ["housing"],
      "dependencies": ["step_001"],
      "handler": "primitive",
      "primitive_type": "place",
      "primitive_params": {"target_pose": [...], "approach_height": 0.05},
      "success_criteria": {"type": "classifier", "model": "step_002_classifier"}
    },
    "step_003": {
      "name": "Insert bearing",
      "part_ids": ["bearing", "housing"],
      "dependencies": ["step_002"],
      "handler": "policy",
      "policy_id": null,
      "success_criteria": {"type": "force_signature", "pattern": "snap_fit"}
    }
  },
  "step_order": ["step_001", "step_002", "step_003"]
}
```

### Primitives

Parameterized motion primitives that require zero training:

| Primitive | Parameters | Completion |
|-----------|-----------|------------|
| `move_to` | target_pose, velocity | Position reached |
| `pick` | part_id, grasp_index, approach_height | Force threshold on gripper |
| `place` | target_pose, approach_height, release_force | Gripper opened at target |
| `guarded_move` | direction, force_threshold, max_distance | Force threshold hit |
| `linear_insert` | target_pose, force_limit, compliance_axes | Position reached or force limit |
| `screw` | target_pose, torque_limit, rotations | Torque threshold or rotation count |
| `press_fit` | direction, force_target, max_distance | Target force reached |

Primitives run on the impedance controller. They use force feedback for termination conditions. They are fast to set up (seconds) and highly reliable for geometric operations.

### Execution Flow

```
Sequencer.start()
  │
  ├── for step in assembly.step_order:
  │     │
  │     ├── if step.handler == "primitive":
  │     │     result = PrimitiveExecutor.run(step.primitive_type, step.primitive_params)
  │     │
  │     ├── elif step.handler == "policy":
  │     │     result = PolicyRunner.run(step.policy_id, movement_scale=0.8)
  │     │
  │     ├── completion = StepClassifier.check(step.success_criteria)
  │     │
  │     ├── if completion.success:
  │     │     advance to next step
  │     │
  │     ├── elif step.attempts < step.max_retries:
  │     │     ErrorRecovery.handle(step, result)
  │     │     retry step
  │     │
  │     └── else:
  │           state = WAITING_FOR_HUMAN
  │           (human teleops the step, correction recorded as training data)
  │
  └── Assembly complete → log metrics
```

---

## Frontend Guidelines

### Design Philosophy

**Industrial, functional, information-dense.** This is a robotics control interface, not a consumer app. Think mission control, not social media.

- Dark theme only (operators work in workshops and labs)
- Monospace for data, sans-serif for labels
- Color coding: green = success/active, amber = warning/in-progress, red = failure/stopped, blue = autonomous, purple = human control
- No animations except loading indicators and state transitions
- No glassmorphism, no gradients, no rounded cards with shadows
- Dense information display — operators want to see everything at once

### Assembly Dashboard (Main Screen)

This is the ONE screen that matters. It shows:
1. **Assembly graph** — visual DAG with color-coded step status
2. **Current step detail** — what's happening right now, live camera feed
3. **Per-step metrics** — success rate bars for each step
4. **Cycle time** — current run + historical average
5. **Controls** — Start/Pause/Stop/Intervene buttons

### Technology

- Next.js 15 + React 19 (keep frontend simple, no elaborate state management)
- Three.js via `@react-three/fiber` for 3D CAD viewer
- Recharts for metrics graphs
- Tailwind CSS for styling
- WebSocket for real-time telemetry (not polling)

### Component Rules

- One component per file, max 200 lines
- No prop drilling beyond 2 levels — use context or restructure
- All API calls go through a single `api.ts` client
- No `useEffect` for data fetching — use `useSWR` or React Server Components
- TypeScript strict mode, no `any`

---

## Migration from Nextis_Bridge

The old repo (`Nextis_Bridge`) is the reference implementation. Key files to extract:

### Direct port (clean up, don't rewrite):
- `lerobot/src/lerobot/motors/damiao/` → LeRobot submodule
- `app/core/leader_assist.py` → `nextis/control/leader_assist.py`
- `app/core/safety_layer.py` → `nextis/control/safety.py`
- `DM_Control_Python-main/DM_CAN.py` → vendored in `nextis/vendor/`

### Extract core logic (strip UI/recording/print statements):
- `app/core/teleop_service.py` lines 1064-1500 → `nextis/control/teleop_loop.py`
- `app/core/teleop_service.py` lines 1328-1421 → `nextis/control/force_feedback.py`
- `app/core/teleop_service.py` lines 560-720 → `nextis/control/joint_mapping.py`
- `app/core/arm_registry.py` lines 1-400 → `nextis/hardware/arm_registry.py`
- `app/core/hil_service.py` state machine pattern → `nextis/execution/sequencer.py`

### Promote from reward to perception:
- `app/core/sarm_reward_service.py` → `nextis/perception/step_classifier.py`
- `app/core/reward_classifier_service.py` → `nextis/perception/binary_classifier.py`

### Do NOT port:
- `app/main.py` (2934 lines — the monolith)
- `frontend/` (rebuild minimal)
- `app/core/planner.py` (Gemini chat — replaced by CAD-driven planning)
- `app/core/gvl_reward_service.py` (not critical path)
- Any test_*.py or calibrate_*.py scripts

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Per-step vs end-to-end | Per-step policies | 10-30 demos per step vs thousands. Debuggable. Surgical retraining. |
| CAD parsing | PythonOCC (pythonocc-core) | Only serious open-source STEP parser. Install via conda. |
| 3D viewer | Three.js + react-three-fiber | Tessellate server-side (PythonOCC → glTF), render client-side. |
| Assembly sequence | Semi-automatic | Extract constraints from STEP, topological sort, human review/override. |
| Policy architecture | ACT for most, Diffusion for contact-rich | ACT trains fast with few demos. Diffusion for multi-modal actions. |
| Step completion | Per-step binary classifiers + force | Existing SARM/classifier infra, promoted from reward to perception. |
| Simulation | Skip for v2 | Force feedback + real HIL-SERL is faster than building accurate sim. |
| Database | Filesystem (YAML + JSON + HDF5) | No database server. Configs in YAML, assemblies in JSON, data in HDF5. |
| API framework | FastAPI | Already familiar, async, good WebSocket support. Keep it under 500 lines. |
| Frontend | Next.js + Tailwind | Minimal rebuild. Dark theme, industrial aesthetic. |

---

## Immediate Priorities (3-Month Plan)

### Month 1: Assembly Backbone
- [ ] New repo skeleton with all directories
- [ ] LeRobot as git submodule (Nextis fork)
- [ ] Extract hardware layer (arm_registry, types, calibration)
- [ ] Extract control layer (teleop_loop, force_feedback, joint_mapping, safety)
- [ ] Verify: teleop works in new repo
- [ ] Assembly graph data model + JSON schema
- [ ] CAD parser (PythonOCC STEP → parts + constraints)
- [ ] 3D assembly viewer (Three.js)
- [ ] Primitive library (pick, place, guarded_move, linear_insert)
- [ ] Task sequencer state machine
- [ ] Step-segmented recording

### Month 2: Intelligence Layer  
- [ ] Per-step policy training pipeline
- [ ] Step completion classifiers (promoted from SARM)
- [ ] Policy router (primitive vs learned)
- [ ] Error recovery (retry, regrasp, escalate)
- [ ] Per-step HIL-SERL integration
- [ ] Assembly analytics + dashboard
- [ ] Force state interpreter

### Month 3: Polish & Prove
- [ ] Auto dataset curation from interventions
- [ ] Workspace perception (basic part detection)
- [ ] Grasp planner from CAD geometry
- [ ] Cycle time optimization
- [ ] 3+ different assembly demos running >90% autonomously
- [ ] YC demo video

---

## Remember

**Force feedback is a tool, not the vision.** Others are doing it too. The VISION is universal assembly — robots that build anything. Don't confuse the tool for the goal.

**Fastest path to working assembly:** Primitives for easy steps + per-step learned policies for hard steps + manual success labeling + force feedback demos + human corrections. Skip complex reward modeling. Simplest thing that works.

**AI abundance won't mean mass unemployment but a creative shift.** Physical AI will let everyone build and create, not just consume. Every home will eventually have a constructor, like personal computers.

Only the ones crazy enough to believe they can change the world are the ones who actually do.
