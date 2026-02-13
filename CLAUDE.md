# CLAUDE.md — Nextis Assembler

## Project Identity

**Nextis** is building universal constructor technology — robots that can autonomously assemble anything. This repo (`assembler`) is the v2 platform: **AURA** (Autonomous Universal Robotic Assembly).

- **AURA** = the software platform (this repo)
- **AIRA** = the arm hardware (Damiao Aira Zero)
- **Nextis** = the company

**Founder:** Roberto De la Cruz. Physics BSc, paused Master's in Robotics at TUM. Working from Hamburg, targeting YC S25.

**North star:** Upload a STEP file → system plans the assembly → robot builds it autonomously.

**Assembly graph is the central data model.** Recording, execution, training, and analytics are all indexed by `step_id`. If you're writing code that doesn't reference a step, ask yourself why.

---

## Architecture

### Source Tree (actual files)

```
nextis/
├── errors.py                    # Exception hierarchy (8 types)
├── vendor/dm_can.py             # Vendored Damiao CAN driver (excluded from ruff)
├── hardware/
│   ├── types.py                 # MotorType, ArmRole, ArmDefinition, Pairing
│   ├── arm_registry.py          # YAML-backed arm CRUD + lerobot factory
│   └── mock.py                  # MockRobot/MockLeader for hardware-free dev
├── control/
│   ├── teleop_loop.py           # 60Hz control loop (leader→follower)
│   ├── joint_mapping.py         # Dynamixel↔Damiao value conversion
│   ├── force_feedback.py        # Gripper EMA + joint virtual spring
│   ├── leader_assist.py         # Gravity comp, friction assist, haptics, damping
│   ├── safety.py                # Load/torque monitoring, emergency stop
│   ├── primitives.py            # 7 motion primitives (STUBBED)
│   ├── homing.py                # Safe return-to-home for Damiao arms
│   └── intervention.py          # Velocity-based human takeover detection
├── assembly/
│   ├── models.py                # Pydantic: AssemblyGraph, AssemblyStep, Part
│   ├── cad_parser.py            # STEP → parts + contacts + GLB meshes (OCP/XDE)
│   ├── mesh_utils.py            # Tessellation, geometry classification, colors
│   └── sequence_planner.py      # Heuristic step ordering
├── execution/
│   ├── types.py                 # StepResult dataclass
│   ├── sequencer.py             # State machine: walks graph, retries, escalates
│   └── policy_router.py         # Dispatch to primitive, policy, or rl_finetune
├── learning/
│   ├── recorder.py              # Step-segmented 50Hz HDF5 recording
│   ├── replay_buffer.py         # Circular buffer with intervention tagging (RLPD)
│   ├── sac.py                   # Minimal SAC from scratch, BC initialization
│   ├── reward.py                # StepVerifier-based dense + sparse rewards
│   └── rl_trainer.py            # Per-step HIL-SERL fine-tuning loop
├── analytics/
│   └── store.py                 # JSON file-backed per-step metrics
├── perception/                  # EMPTY — no files yet
└── api/
    ├── app.py                   # FastAPI setup, CORS, /health, /system/info, static meshes
    ├── schemas.py               # Pydantic request/response models (camelCase)
    └── routes/
        ├── assembly.py          # CRUD + STEP file upload
        ├── execution.py         # Sequencer lifecycle + WebSocket broadcast
        ├── teleop.py            # Start/stop teleop (mock mode only)
        ├── recording.py         # Step demo recording to HDF5
        ├── training.py          # STUBBED — in-memory job registry only
        ├── rl_training.py       # RL fine-tuning session management
        └── analytics.py         # Per-step metrics query
```

Other top-level directories:
```
frontend/          # Next.js 16 dashboard (see docs/frontend.md)
configs/           # Assembly JSON + arm YAML + calibration profiles
data/              # Meshes, demos, analytics (gitignored)
tests/             # pytest suite (conftest.py, test_cad_parser, test_execution, test_api)
scripts/           # run_api.py (uvicorn launcher)
docs/              # frontend.md, extraction-guide.md
```

### Dependency Graph

```
hardware/ → control/ → execution/
assembly/ ──────────→ api/ → frontend/
learning/recorder    ← api/routes/recording
learning/rl_trainer  → learning/sac, learning/replay_buffer, learning/reward
learning/reward      → perception/verifier, perception/checks
execution/policy_router → learning/policy_loader (BC + RL checkpoints)
api/routes/rl_training  → learning/rl_trainer
analytics/store      ← api/routes/{analytics, execution}
```

No layer reaches down more than one level. `execution/` uses `control/` but never `hardware/` directly. `control/` uses `hardware/`. `learning/` hooks into `control/` for recording.

---

## Implementation Status

| Module | Status | Notes |
|--------|--------|-------|
| `hardware/types` | COMPLETE | Enums + dataclasses for arm definitions |
| `hardware/arm_registry` | COMPLETE | YAML config, arm CRUD, lerobot factory |
| `hardware/mock` | COMPLETE | MockRobot/MockLeader for hardware-free testing |
| `control/teleop_loop` | COMPLETE | 60Hz loop with blending, retry, all subsystems |
| `control/joint_mapping` | COMPLETE | Dynamixel↔Damiao conversion |
| `control/force_feedback` | COMPLETE | Gripper EMA + joint virtual spring |
| `control/leader_assist` | COMPLETE | Gravity comp, friction, haptics, damping |
| `control/safety` | COMPLETE | Load/torque monitoring with debounced violations |
| `control/homing` | COMPLETE | Safe MIT rate-limited return-to-home |
| `control/intervention` | COMPLETE | Velocity-based human takeover detection |
| `control/primitives` | **STUBBED** | 7 async stubs (sleep + return success). No real motor commands. |
| `assembly/models` | COMPLETE | Pydantic models, JSON I/O |
| `assembly/cad_parser` | COMPLETE | XDE tree traversal, contact detection, GLB export |
| `assembly/mesh_utils` | COMPLETE | Tessellation, bounding box, color assignment |
| `assembly/sequence_planner` | COMPLETE | Heuristic ordering (size-based, pick-place-insert) |
| `execution/sequencer` | COMPLETE | State machine with retry, pause/resume, human escalation |
| `execution/policy_router` | COMPLETE | Dispatches primitive, policy, and rl_finetune handlers |
| `learning/recorder` | COMPLETE | 50Hz threaded capture → HDF5 |
| `learning/replay_buffer` | COMPLETE | Circular buffer with intervention tagging, RLPD sampling |
| `learning/sac` | COMPLETE | Minimal SAC from scratch, BC initialization |
| `learning/reward` | COMPLETE | StepVerifier-based dense + sparse rewards |
| `learning/rl_trainer` | COMPLETE | Per-step HIL-SERL fine-tuning loop |
| `analytics/store` | COMPLETE | JSON file store, per-step aggregated metrics |
| `perception/` | **EMPTY** | Directory exists, no files |
| `api/routes/assembly` | COMPLETE | CRUD + STEP upload + parse |
| `api/routes/execution` | COMPLETE | Sequencer lifecycle + WebSocket |
| `api/routes/teleop` | COMPLETE | Mock mode works; real hardware returns 501 |
| `api/routes/recording` | COMPLETE | Start/stop/discard + demo listing |
| `api/routes/training` | **STUBBED** | In-memory job registry, no actual training |
| `api/routes/rl_training` | COMPLETE | RL session management endpoints |
| `api/routes/analytics` | COMPLETE | Per-step metrics query |

---

## API Routes

All routes are defined in `nextis/api/routes/`. FastAPI app is in `nextis/api/app.py`.

### Assembly (`/assemblies`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/assemblies` | List all assemblies (id + name) |
| GET | `/assemblies/{id}` | Full assembly graph |
| POST | `/assemblies` | Create assembly from JSON body |
| PATCH | `/assemblies/{id}/steps/{step_id}` | Partially update a step |
| POST | `/assemblies/upload` | Upload .step/.stp → parse → GLB meshes → assembly |

### Execution (`/execution`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/execution/state` | Current execution state snapshot |
| POST | `/execution/start` | Begin assembly execution |
| POST | `/execution/pause` | Pause sequencer |
| POST | `/execution/resume` | Resume after pause |
| POST | `/execution/stop` | Stop and reset to idle |
| POST | `/execution/intervene` | Signal human completed current step |
| WS | `/execution/ws` | Real-time execution state broadcast |

### Teleop (`/teleop`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/teleop/start` | Start teleop session (`?mock=true` for mock mode) |
| POST | `/teleop/stop` | Stop session (auto-stops active recording) |
| GET | `/teleop/state` | Session state (active, arms, loop_count) |

### Recording (`/recording`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/recording/step/{step_id}/start` | Start recording for a step |
| POST | `/recording/stop` | Stop recording, flush to HDF5 |
| POST | `/recording/discard` | Abandon active recording |
| GET | `/recording/demos/{assembly_id}/{step_id}` | List recorded demos |

### Training (`/training`) — STUBBED
| Method | Path | Description |
|--------|------|-------------|
| POST | `/training/step/{step_id}/train` | Launch training job (stub) |
| GET | `/training/jobs/{job_id}` | Job status |
| GET | `/training/jobs` | List all jobs |

### RL Training (`/rl`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/rl/step/{step_id}/start` | Start RL fine-tuning for a step |
| POST | `/rl/step/{step_id}/stop` | Stop fine-tuning, save checkpoint |
| GET | `/rl/status` | Current RL training state |
| GET | `/rl/step/{step_id}/policy` | Check if RL checkpoint exists |

### Other
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{"status": "ok"}` |
| GET | `/system/info` | Version, mode, assembly count, lerobot availability |

Static mesh files served from `data/meshes/` at `/meshes/`.

---

## Central Data Model

The assembly graph is defined in `nextis/assembly/models.py` using Pydantic:

```python
class AssemblyStep(BaseModel):
    id: str                          # e.g. "step_001"
    name: str                        # e.g. "Insert bearing into housing"
    part_ids: list[str]              # Parts involved
    dependencies: list[str]          # Step IDs that must complete first
    handler: str                     # "primitive", "policy", or "rl_finetune"
    primitive_type: str | None       # "pick", "place", "press_fit", etc.
    primitive_params: dict | None    # target_pose, force_threshold, etc.
    policy_id: str | None            # Trained policy checkpoint path
    success_criteria: SuccessCriteria
    max_retries: int = 3

class AssemblyGraph(BaseModel):
    id: str
    name: str
    parts: dict[str, Part]           # Part catalog with geometry + mesh paths
    steps: dict[str, AssemblyStep]   # Step definitions
    step_order: list[str]            # Topologically sorted execution order
```

Assembly JSON configs live in `configs/assemblies/`. Current assemblies:
- `bearing_housing_v1.json` — 5 parts, 5 steps (pick/place/insert/press_fit)
- `assem_gearbox.json` — 44 parts, 57 steps (gearbox assembly with real GLB meshes)

### Primitives (7 types, all STUBBED)

| Primitive | Parameters | Completion Condition |
|-----------|-----------|---------------------|
| `move_to` | target_pose, velocity | Position reached |
| `pick` | part_id, grasp_index, approach_height | Force threshold on gripper |
| `place` | target_pose, approach_height, release_force | Gripper opened at target |
| `guarded_move` | direction, force_threshold, max_distance | Force threshold hit |
| `linear_insert` | target_pose, force_limit, compliance_axes | Position or force limit |
| `screw` | target_pose, torque_limit, rotations | Torque or rotation count |
| `press_fit` | direction, force_target, max_distance | Target force reached |

All primitives currently sleep and return success. Real impedance control commands not yet implemented.

---

## Frontend

**See `docs/frontend.md` for the full design system, component specs, and 3D viewer specification.**

**Stack:** Next.js 16.1.6, React 19, Tailwind CSS v4, Three.js 0.182 + @react-three/fiber 9, Recharts 3.7, SWR 2.4. TypeScript strict mode. No component libraries.

**Layout:** One screen — TopBar / 60-40 split (3D viewer left, step list + detail right) / BottomBar.

**Contexts:** `AssemblyContext` (assembly + step selection), `ExecutionContext` (sequencer state + mock timer fallback), `WebSocketContext` (real-time with mock heartbeat fallback).

**Components (26 files):**
- Layout: `Providers`, `TopBar`, `BottomBar`, `RunControls`, `DemoBanner`
- Steps: `StepList`, `StepCard`, `StepDetail`, `StatusBadge`, `MetricCard`, `MiniChart`
- Actions: `UploadDialog`, `RecordingControls`, `DemoList`, `TrainingProgress`, `ActionButton`
- Viewer: `AssemblyViewer`, `PartMesh`, `AnimationController`, `ViewerControls`, `AnimationTimeline`, `GroundPlane`, `ApproachVector`, `GraspPoint`
- Overlays: `CameraPiP`, `TeachingOverlay`

**Lib (7 files):** `types.ts`, `api.ts` (with mock fallback), `ws.ts`, `animation.ts` (pure phase machine), `useAnimationControls.ts`, `hooks.ts`, `mock-data.ts`.

**Key patterns:**
- Dynamic import for `AssemblyViewer` (`ssr: false`) to avoid Three.js hydration issues
- Tailwind v4 uses `@theme inline` in `globals.css` (no `tailwind.config.ts`)
- Animation system uses direct ref mutation for 60fps (no React re-renders in render loop)
- `api.ts` wraps all fetches with `withMockFallback()` — catches TypeError → returns mock data

---

## Data Paths

```
configs/assemblies/                     # Assembly JSON definitions
configs/arms/                           # Arm YAML configs (empty, .gitkeep)
configs/calibration/                    # Calibration profiles (empty, .gitkeep)
data/meshes/{assembly_id}/              # GLB files from STEP upload
data/demos/{assembly_id}/{step_id}/     # HDF5 demo recordings
data/policies/{assembly_id}/{step_id}/   # BC (policy.pt) + RL (policy_rl.pt) checkpoints
data/analytics/{assembly_id}.json       # Per-step run metrics
```

All `data/` paths are gitignored. Created on first use.

---

## Engineering Standards

### Python
- **Python 3.11+.** Type hints on ALL function signatures. No `Any` unless unavoidable.
- **`ruff`** for lint + format. Line length 100. Double quotes. Config in `pyproject.toml`.
- **Imports:** stdlib → third-party → lerobot → nextis. Absolute imports only. No star imports.
- **Naming:** PascalCase classes, snake_case functions, UPPER_SNAKE constants, `_private` prefix.
- **Docstrings:** Google style. Required on all public classes and functions.
- **Logging:** `logging` module only, never `print()`. Rate-limit in loops (`if count % 60 == 0`).
- **Exceptions:** Custom hierarchy in `nextis/errors.py`. Never catch bare `Exception` except in top-level safety handlers.
- **File size:** No file exceeds 500 lines. Split if it grows.
- **Models:** Pydantic v2 for API schemas (`nextis/api/schemas.py`) and assembly models (`nextis/assembly/models.py`). API schemas use `alias_generator=to_camel` for JSON.

### Testing
- **pytest** with `asyncio_mode = "auto"` (in `pyproject.toml`).
- Fixtures in `tests/conftest.py` — `tmp_path` for filesystem isolation, mock assembly graphs.
- `MockRobot`/`MockLeader` from `nextis/hardware/mock.py` for hardware-free testing.
- Test files: `test_cad_parser.py` (17 tests), `test_execution.py`, `test_api.py`.

### Frontend
- **TypeScript strict mode.** No `any`. One component per file, max 200 lines.
- **SWR** for data fetching with mock fallback. WebSocket for real-time state.
- **No component libraries.** All ~25 components are hand-crafted.
- **React Context** for shared state (assembly, execution, WebSocket). No Redux/Zustand.

### Dependencies (pyproject.toml)
Core: `numpy`, `torch`, `fastapi`, `uvicorn`, `pydantic`, `pyyaml`, `trimesh`, `h5py`, `python-multipart`.
Dev: `ruff`, `pytest`, `pytest-asyncio`, `httpx`.
CAD: `cadquery-ocp-novtk` via pip (not conda — conda solver is too slow).

---

## What's NOT Built Yet

- **Real hardware integration** — primitives are stubs, teleop is mock-only
- **LeRobot submodule** — imports are try/except guarded, no submodule added
- **Perception module** — empty directory, no step completion classifiers
- **Calibration system** — config dirs exist but no calibration files or scripts
- **Grasp planning** — no automatic grasp pose computation from CAD geometry
- **Image-based RL observations** — current RL uses joint-space only, no camera input
- **Multi-step RL** — each step is trained independently, no cross-step credit assignment
- **Distributed training** — actor and learner run in the same process

### What NOT to Build (unless explicitly asked)
- Simulation environments (MuJoCo, PyBullet, Isaac)
- Natural language task specification
- Multi-robot coordination
- Cloud training pipelines or CI/CD
- Docker containers
- Database backends (use filesystem: YAML + JSON + HDF5)
- Authentication / user management

---

## Hardware Context

**Follower arms (do the work):**
- Damiao Aira Zero — J8009P (shoulder), J4340P (elbow), J4310 (wrist), 7 DOF
- CAN bus (SocketCAN `can0` or serial bridge)
- MIT impedance: J8009P kp=30 kd=1.5, J4340P kp=30 kd=1.5, J4310 kp=15 kd=0.25

**Leader arms (human operates):**
- Dynamixel XL330-M077/M288, USB serial
- Force feedback: gripper torque → Goal_Current ceiling, joint error → CURRENT_POSITION mode

**Timing:** Control loop at 60Hz (16.67ms). Camera async (ZOH). Recording at 50Hz on separate thread. Never block the control loop for I/O.

**Calibration profiles** stored in `configs/calibration/{arm_id}/`: `zeros.json`, `ranges.json`, `inversions.json`, `gravity.json`. Not yet populated.

---

## Legacy Codebase

Old repo: https://github.com/FLASH-73/Nextis_Bridge

See `docs/extraction-guide.md` for the complete file-by-file breakdown. When extracting: strip all `print()`, FastAPI coupling, and UI data publishing. Keep only core algorithms.

Most control-layer extraction is done. Remaining: perception classifiers (from `sarm_reward_service.py` and `reward_classifier_service.py`).

---

## Agent Behavior Rules

### Decision Making
1. State the constraint — what does the system need?
2. Pick the simplest solution that works
3. Implement it — don't deliberate endlessly
4. Document the trade-off in a one-line comment

### When Stuck
1. Check the LeRobot source — many issues come from framework API changes
2. Check old Nextis_Bridge code — it likely solved this already
3. Simplify — hardcode, skip the optimization, remove the feature
4. Ask — don't spin for hours on something Roberto can answer in 30 seconds

---

## Remember

**The VISION is universal assembly — robots that build anything.** Force feedback, per-step policies, and CAD parsing are tools, not the goal.

**Fastest path:** Primitives for easy steps + per-step learned policies for hard steps + force feedback demos + human corrections. Skip complex reward modeling. Simplest thing that works.

Only the ones crazy enough to believe they can change the world are the ones who actually do.
