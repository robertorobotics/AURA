# Nextis v2 — File Extraction Guide
## What to take from Nextis_Bridge into the new repo

---

## TIER 1: COPY DIRECTLY (your core IP — hard to rebuild)

These files contain months of hardware debugging, motor tuning, and protocol work.
Copy them into the new repo and refactor imports.

### LeRobot Hardware Drivers (your fork — keep as git submodule)
```
lerobot/src/lerobot/motors/damiao/damiao.py      (1515 lines) — Damiao CAN bus driver
lerobot/src/lerobot/motors/damiao/tables.py       (specs, gains, limits)
lerobot/src/lerobot/motors/damiao/__init__.py
lerobot/src/lerobot/motors/motors_bus.py           (50K — base class for all motor buses)
lerobot/src/lerobot/motors/dynamixel/             (Dynamixel XL330 driver — leader arms)
lerobot/src/lerobot/motors/feetech/               (Feetech STS3215 — SO100/Umbra)
lerobot/src/lerobot/motors/encoding_utils.py

lerobot/src/lerobot/robots/damiao_follower/       (your custom Damiao robot class)
lerobot/src/lerobot/teleoperators/dynamixel_leader/ (leader arm teleoperator)
lerobot/src/lerobot/cameras/                      (OpenCV + RealSense wrappers)

lerobot/src/lerobot/datasets/                     (LeRobot dataset format — DON'T FORK, use as-is)
lerobot/src/lerobot/utils/robot_utils.py          (precise_sleep, etc.)
lerobot/src/lerobot/utils/constants.py            (OBS_STR, ACTION)
```

**Decision: Keep entire `lerobot/` as a git submodule.** You've modified files inside it
(damiao driver, damiao_follower robot). Best approach: maintain your own fork of LeRobot
as a submodule, and periodically rebase on upstream.

### DM_CAN Low-Level Driver
```
DM_Control_Python-main/DM_CAN.py                  (625 lines) — raw CAN protocol
```
This is the foundation your damiao.py builds on. Keep as a vendored dependency.

---

## TIER 2: EXTRACT & REFACTOR (valuable logic, needs decoupling)

These files have critical logic mixed with FastAPI/UI concerns.
Extract the core algorithms into clean classes.

### From teleop_service.py (2154 lines) — EXTRACT THESE PIECES:
```python
# 1. The 60Hz control loop (_teleop_loop method, lines 1064-1500+)
#    → new file: nextis/control/teleop_loop.py
#    Core: leader read → joint mapping → value conversion → follower write
#    Remove: all recording logic, all UI data publishing, print statements

# 2. Force feedback (lines 1328-1421)
#    → new file: nextis/control/force_feedback.py
#    - Gripper: follower torque → leader Goal_Current (EMA filter + deadzone + ramp)
#    - Joint: CURRENT_POSITION mode virtual spring (position error → current)
#    Clean, self-contained, ~100 lines

# 3. Joint mapping & value conversion (lines 560-720)
#    → new file: nextis/control/joint_mapping.py
#    - Dynamixel→Damiao name mapping
#    - rad→percent conversion
#    - Pairing-based mapping from arm registry
#    - Leader calibration range lookup

# 4. Startup blend (lines 1224-1290ish)
#    → integrate into teleop_loop.py
#    Ramps from follower's current position to avoid jerks

# 5. Homing (lines 1025-1062)
#    → new file: nextis/control/homing.py
#    Smooth return to home position using rate limiter
```

### From arm_registry.py (1304 lines) — EXTRACT:
```python
# 1. ArmDefinition, Pairing, MotorType, ArmRole dataclasses (lines 1-88)
#    → new file: nextis/hardware/types.py
#    Clean data models, no dependencies

# 2. ArmRegistryService core logic (lines 90-400ish)
#    → new file: nextis/hardware/arm_registry.py
#    - Config loading/saving (YAML)
#    - Arm connection management
#    - Pairing resolution
#    Remove: motor recovery (1000+ lines), legacy migration, REST-specific methods

# 3. Motor recovery (lines 700-1220)
#    → new file: nextis/hardware/motor_recovery.py (or drop for now)
#    Nice to have but not critical path for v2
```

### From safety_layer.py (178 lines) — COPY MOSTLY AS-IS:
```python
# → new file: nextis/control/safety.py
# Clean already. Just remove the import of MagicMock and clean up logging.
# Add: assembly-context safety (e.g., force limits per assembly step)
```

### From leader_assist.py (242 lines) — COPY AS-IS:
```python
# → new file: nextis/control/leader_assist.py
# Already clean. Gravity comp, friction assist, haptic reflection.
# No refactoring needed.
```

### From hil_service.py (1415 lines) — EXTRACT:
```python
# 1. HILMode state machine (IDLE → AUTONOMOUS → HUMAN → PAUSED)
#    → This pattern becomes the basis for your TASK SEQUENCER
#    → new file: nextis/execution/sequencer.py (rewritten, but use this as reference)

# 2. Intervention detection logic (leader velocity spike → takeover)
#    → new file: nextis/control/intervention.py
#    ~50 lines of clean logic, very reusable

# 3. Movement scale safety (cap autonomous joint deltas)
#    → integrate into nextis/execution/sequencer.py
```

### From rl_service.py (912 lines) — EXTRACT:
```python
# 1. RLConfig dataclass (lines 39-80)
#    → new file: nextis/learning/rl_config.py

# 2. Actor-learner architecture (actor thread + learner process + queues)
#    → new file: nextis/learning/rl_trainer.py
#    This is solid. Main refactor: make it step-aware (accept step_id parameter)

# 3. Dual replay buffer management
#    → Keep using lerobot/src/lerobot/rl/buffer.py directly
```

### From sarm_reward_service.py (856 lines) — PROMOTE:
```python
# → new file: nextis/perception/step_classifier.py
# SARM does stage-aware reward modeling (CLIP features → 0-1 progress)
# In v2 this becomes your primary STEP COMPLETION DETECTOR
# Refactor: rename from "reward" to "completion", add binary threshold
```

### From reward_classifier_service.py (560 lines) — PROMOTE:
```python
# → new file: nextis/perception/binary_classifier.py
# Binary CNN: success vs failure from last-N frames
# In v2: per-step success classifier
# Refactor: train per step_id, not per task
```

### From training_service.py (1784 lines) — EXTRACT:
```python
# → new file: nextis/learning/trainer.py
# Core: dataset loading, policy instantiation, training loop, checkpoint saving
# Refactor: accept step_id to train per-step policies
# Remove: all FastAPI job management, progress polling endpoints
```

### From recorder.py — EXTRACT:
```python
# The recording logic is actually mostly in teleop_service.py (the _recording_capture_loop)
# Plus LeRobot dataset creation in recorder.py
# → new file: nextis/data/recorder.py
# Refactor: accept step_id for step-segmented recording
# Remove: session/episode REST management, UI concerns
```

### From calibration_service.py (1034 lines) — EXTRACT:
```python
# → new file: nextis/hardware/calibration.py
# Core: homing, range discovery, encoder zeroing, gravity compensation calibration
# Remove: wizard state machine (that's UI), REST endpoints
```

---

## TIER 3: REFERENCE ONLY (don't copy, learn from)

### main.py (2934 lines)
The FastAPI monolith. Don't copy any of it. But READ it to understand:
- How services are wired together (SystemState class)
- What endpoints exist (your new API will be much smaller)
- Where the coupling points are

### orchestrator.py (195 lines)
Single-policy deployment. Your new task sequencer replaces this entirely,
but the inference loop pattern (load policy → run at 30Hz → send actions) is useful.

### planner.py (309 lines)
Gemini task DAG generation. The DAG concept is right for assembly graphs,
but the implementation is completely replaced by CAD-driven planning.

### camera_service.py (425 lines)
Camera management. Useful reference but LeRobot's camera abstraction
handles most of this. Just need a thin wrapper.

### dataset_service.py (732 lines)
Dataset CRUD. Replaced by step-segmented dataset management.

---

## TIER 4: DROP ENTIRELY

```
frontend/                          — Rebuild from scratch (minimal)
app/main.py                        — 2934-line FastAPI monolith
app/core/shared_memory.py          — Replaced by cleaner state management
app/core/gvl_reward_service.py     — Gemini reward, not critical path
app/core/planner.py                — Gemini chat planning
app/core/camera_discovery.py       — Absorbed into camera_service
examples_for_damiao/               — Test scripts
test_*.py                          — One-off diagnostics
calibrate_*.py                     — One-off scripts
configure_all_motors_mit.py        — One-time setup
openarm_teleop-main/               — C++ teleop (superseded)
openarm_can-main/                  — C++ CAN lib (Python driver supersedes)
Papers/                            — Reference docs (keep in old repo)
outputs/                           — Captured images
data/                              — Raw data
```

---

## NEW REPO STRUCTURE

```
nextis-assembler/
├── README.md
├── pyproject.toml
├── lerobot/                        # Git submodule (your fork)
│
├── nextis/
│   ├── __init__.py
│   │
│   ├── hardware/                   # Motor control & arm management
│   │   ├── types.py               # ArmDefinition, Pairing, MotorType, ArmRole
│   │   ├── arm_registry.py        # Arm registration, connection, pairing
│   │   ├── calibration.py         # Joint calibration, range discovery
│   │   └── motor_recovery.py      # Optional: motor diagnostics
│   │
│   ├── control/                    # Real-time control (60Hz loop)
│   │   ├── teleop_loop.py         # Core leader→follower control loop
│   │   ├── force_feedback.py      # Gripper + joint force feedback
│   │   ├── joint_mapping.py       # Cross-motor-type joint mapping
│   │   ├── leader_assist.py       # Gravity comp, friction, haptics
│   │   ├── intervention.py        # Human takeover detection
│   │   ├── homing.py              # Safe return to home position
│   │   ├── safety.py              # Torque limits, E-stop, quarantine
│   │   └── primitives.py          # NEW: parameterized motion primitives
│   │
│   ├── assembly/                   # NEW: Assembly intelligence
│   │   ├── models.py              # AssemblyGraph, AssemblyStep, Part
│   │   ├── cad_parser.py          # STEP/IGES → parts + constraints
│   │   ├── sequence_planner.py    # Topological sort, dependency analysis
│   │   ├── grasp_planner.py       # Grasp poses from geometry
│   │   └── viewer.py              # 3D mesh export for Three.js
│   │
│   ├── execution/                  # NEW: Assembly execution engine
│   │   ├── sequencer.py           # Assembly graph state machine
│   │   ├── policy_router.py       # Primitive vs learned policy dispatch
│   │   └── error_recovery.py      # Retry, regrasp, escalate logic
│   │
│   ├── perception/                 # NEW: Scene understanding
│   │   ├── step_classifier.py     # Per-step completion detection (from SARM)
│   │   ├── binary_classifier.py   # Success/failure from vision (from reward_classifier)
│   │   └── force_interpreter.py   # Force signature detection
│   │
│   ├── learning/                   # Training & improvement
│   │   ├── recorder.py            # Step-segmented data collection
│   │   ├── trainer.py             # Per-step policy training
│   │   ├── rl_trainer.py          # HIL-SERL (step-aware)
│   │   └── auto_curator.py        # NEW: intervention → training data
│   │
│   ├── analytics/                  # NEW: Assembly metrics
│   │   ├── metrics.py             # Per-step success rate, cycle time
│   │   └── dashboard_data.py      # Data for frontend dashboard
│   │
│   └── api/                        # Thin API layer
│       ├── app.py                  # FastAPI app (minimal, <500 lines)
│       ├── routes/
│       │   ├── assembly.py         # CAD upload, graph management
│       │   ├── execution.py        # Start/stop/monitor assembly runs
│       │   ├── teleop.py           # Teleoperation control
│       │   ├── recording.py        # Step-segmented recording
│       │   ├── training.py         # Per-step training
│       │   └── analytics.py        # Metrics and dashboard data
│       └── websocket.py            # Real-time telemetry streaming
│
├── frontend/                       # Minimal Next.js (rebuild lean)
│   ├── app/
│   │   ├── page.tsx               # Assembly dashboard (main screen)
│   │   └── layout.tsx
│   ├── components/
│   │   ├── AssemblyViewer3D.tsx    # Three.js CAD viewer
│   │   ├── AssemblyGraph.tsx       # Step DAG visualization
│   │   ├── StepMetrics.tsx         # Per-step success rates
│   │   ├── TeleopControls.tsx      # Minimal teleop UI
│   │   ├── ExecutionMonitor.tsx    # Live assembly progress
│   │   └── RecordingPanel.tsx      # Step-segmented recording
│   └── package.json
│
├── configs/                        # Hardware & assembly configs
│   ├── arms/                       # Per-arm YAML configs
│   ├── assemblies/                 # Assembly graph definitions
│   └── calibration/                # Calibration profiles
│
├── scripts/
│   ├── setup_can.sh               # CAN bus setup
│   └── calibrate.py               # Calibration CLI
│
└── tests/
    ├── test_teleop.py
    ├── test_sequencer.py
    └── test_assembly_graph.py
```

---

## MIGRATION ORDER (what to do first)

### Week 1: Skeleton + Hardware
1. Create new repo with structure above
2. Add lerobot as git submodule (your fork)
3. Copy DM_CAN.py as vendored dependency
4. Extract `nextis/hardware/types.py` and `nextis/hardware/arm_registry.py`
5. Extract `nextis/control/teleop_loop.py` (strip recording, strip UI)
6. Extract `nextis/control/force_feedback.py`
7. Extract `nextis/control/joint_mapping.py`
8. Extract `nextis/control/safety.py` and `nextis/control/leader_assist.py`
9. **TEST: Can you teleop the arms from the new repo?** ← First milestone

### Week 2: Assembly Backbone
10. Create `nextis/assembly/models.py` (AssemblyGraph, AssemblyStep, Part)
11. Create `nextis/assembly/cad_parser.py` (PythonOCC STEP parser)
12. Create `nextis/control/primitives.py` (move_to, pick, place, guarded_move)
13. Create `nextis/execution/sequencer.py` (state machine from HIL pattern)
14. **TEST: Can you load a STEP file and execute primitives?** ← Second milestone

### Week 3: Learning Pipeline
15. Extract `nextis/learning/recorder.py` (step-segmented)
16. Extract `nextis/learning/trainer.py` (per-step training)
17. Promote SARM → `nextis/perception/step_classifier.py`
18. Create `nextis/execution/policy_router.py`
19. **TEST: Record step demos, train per-step, execute with sequencer** ← Third milestone
