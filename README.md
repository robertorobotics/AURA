# AURA — Autonomous Universal Robotic Assembly

**AURA is the brain. AIRA is the arm.**

Upload a CAD file → auto-generate assembly plan → teach the hard steps → run autonomously.

<p align="center">
  <img src="demo/aura%20v1.gif" alt="AURA demo — upload CAD, plan assembly, execute" width="800"/>
</p>

## What It Does

1. **Parse** — Upload a STEP file, extract parts and geometry, export GLB meshes
2. **Plan** — Auto-generate assembly sequence from contact analysis and heuristics
3. **Teach** — Teleoperate hard steps with force feedback, record demonstrations
4. **Learn** — Train per-step policies from demos (ACT, Diffusion Policy via LeRobot)
5. **Run** — Execute assembly autonomously with retry + human fallback

## Quick Start

```bash
# Backend
conda activate nextis
pip install -e ".[dev]"
python scripts/run_api.py

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Open http://localhost:3000

## Stack

- **Backend:** Python 3.11, FastAPI, Pydantic v2, PythonOCC (cadquery-ocp)
- **Frontend:** Next.js 16, React 19, Three.js, Tailwind v4
- **Learning:** LeRobot (coming)
- **Hardware:** Damiao J8009P/J4340P/J4310 (CAN), Dynamixel XL330 (serial)

## Project Structure

```
nextis/
├── hardware/       # Motor control, arm registry, mock hardware
├── control/        # 60Hz teleop loop, force feedback, safety, homing
├── assembly/       # CAD parsing (STEP → GLB), layout, sequence planning
├── execution/      # Task sequencer, policy router, state machine
├── learning/       # HDF5 recording, replay buffer, SAC, RL trainer
├── analytics/      # JSON-backed per-step metrics
├── perception/     # Step completion classifiers (planned)
└── api/            # FastAPI — HTTP/WebSocket layer + routes
frontend/           # Next.js dashboard (3D viewer, animation, controls)
configs/            # Assembly JSON + arm YAML
scripts/            # API launcher, demo scripts
```

**Central data model:** Everything is indexed by the assembly graph. Recording, training, execution, and analytics are all per-step.

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /system/info` | Version, mode (mock/hardware), assembly count |
| `GET /assemblies` | List assemblies |
| `POST /assemblies/upload` | Upload STEP file → assembly graph + GLB meshes |
| `POST /execution/start` | Start assembly (`assemblyId`, optional `speed`) |
| `WS /execution/ws` | Real-time execution state |

## Development

```bash
ruff check nextis/ tests/
ruff format nextis/ tests/
pytest
```

See [CLAUDE.md](CLAUDE.md) for full architecture documentation.
