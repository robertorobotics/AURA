#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# AURA — Autonomous Universal Robotic Assembly
# One-command startup: conda env + deps + backend + frontend
# ──────────────────────────────────────────────────────────────────────────────
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Constants ─────────────────────────────────────────────────────────────────
CONDA_ENV="nextis"
BACKEND_PORT=8000
FRONTEND_PORT=3000
HEALTH_URL="http://localhost:${BACKEND_PORT}/health"
HEALTH_TIMEOUT=30
FRONTEND_TIMEOUT=30
LOG_DIR="$SCRIPT_DIR/logs"

# ── Colors & helpers ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()   { echo -e "${BLUE}>>>${NC} ${BOLD}$1${NC}"; }
ok()     { echo -e "  ${GREEN}[OK]${NC} $1"; }
fail()   { echo -e "  ${RED}[FAIL]${NC} $1"; }
warn()   { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
header() { echo -e "\n${BOLD}=== $1 ===${NC}"; }
die()    { fail "$1"; exit 1; }

# ── Cleanup (trap) ────────────────────────────────────────────────────────────
BACKEND_PID=""
FRONTEND_PID=""
CLEANING_UP=false

cleanup() {
    # Prevent re-entrancy (trap fires for each signal + EXIT)
    $CLEANING_UP && return
    CLEANING_UP=true

    echo ""
    header "Shutting down"

    for pid_var in BACKEND_PID FRONTEND_PID; do
        local pid="${!pid_var}"
        [[ -z "$pid" ]] && continue
        if kill -0 "$pid" 2>/dev/null; then
            local pgid
            pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ') || true
            if [[ -n "$pgid" && "$pgid" != "0" ]]; then
                kill -- -"$pgid" 2>/dev/null || true
            fi
            kill "$pid" 2>/dev/null || true
        fi
    done

    sleep 1

    # Force-kill anything still on our ports
    local remaining
    remaining=$(ss -tlnp "sport = :$BACKEND_PORT or sport = :$FRONTEND_PORT" 2>/dev/null \
        | grep -oP 'pid=\K[0-9]+' | sort -u) || true
    if [[ -n "$remaining" ]]; then
        for pid in $remaining; do
            kill -9 "$pid" 2>/dev/null || true
        done
    fi

    echo -e "\n${GREEN}${BOLD}AURA stopped.${NC}"
}
trap cleanup EXIT INT TERM

# ── Phase 1: Prerequisites ────────────────────────────────────────────────────
header "Checking prerequisites"

for cmd in curl node npm; do
    command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required but not found"
done

# Find conda — try known path first, then PATH
CONDA_PATH=""
if [[ -x "$HOME/miniconda3/bin/conda" ]]; then
    CONDA_PATH="$HOME/miniconda3/bin/conda"
elif [[ -x "$HOME/anaconda3/bin/conda" ]]; then
    CONDA_PATH="$HOME/anaconda3/bin/conda"
elif command -v conda >/dev/null 2>&1; then
    CONDA_PATH="$(command -v conda)"
fi
[[ -z "$CONDA_PATH" ]] && die "conda not found. Install: https://docs.conda.io/en/latest/miniconda.html"

ok "Prerequisites found (node $(node -v), npm $(npm -v), conda)"

# ── Phase 2: Conda environment ────────────────────────────────────────────────
header "Activating conda environment"

# Conda's shell hooks use unset variables — must relax strict mode
set +eu
eval "$("$CONDA_PATH" shell.bash hook)" 2>/dev/null

# Deactivate any inherited env (e.g. from parent shell) to get a clean state
conda deactivate 2>/dev/null || true

if ! conda env list 2>/dev/null | grep -qw "$CONDA_ENV"; then
    set -e
    warn "Conda env '$CONDA_ENV' not found — creating it..."
    if [[ -f "$SCRIPT_DIR/environment.yml" ]]; then
        conda env create -f "$SCRIPT_DIR/environment.yml" || die "Failed to create conda env"
    else
        conda create -n "$CONDA_ENV" python=3.11 pip -y || die "Failed to create conda env"
    fi
    set +eu
fi

conda activate "$CONDA_ENV"
set -e

# Verify the right Python is active
ACTIVE_PYTHON="$(which python 2>/dev/null || true)"
if [[ "$ACTIVE_PYTHON" != *"/envs/$CONDA_ENV/"* ]]; then
    die "Conda activation failed. Got: $ACTIVE_PYTHON (expected env: $CONDA_ENV)"
fi
ok "Conda env '$CONDA_ENV' active ($(python --version))"

# ── Phase 3: Python dependencies ──────────────────────────────────────────────
header "Checking Python dependencies"

if python -c "import nextis" 2>/dev/null; then
    ok "nextis package installed"
else
    info "Installing Python dependencies..."
    pip install -e "$SCRIPT_DIR[dev]" || die "pip install failed"
    ok "Python dependencies installed"
fi

if python -c "import lerobot" 2>/dev/null; then
    ok "lerobot available"
else
    warn "lerobot not found — hardware connections will be mock-only"
    warn "Run: git clone --depth 1 https://github.com/FLASH-73/Nextis_Bridge.git /tmp/nb && cp -r /tmp/nb/lerobot . && rm -rf /tmp/nb"
fi

if python -c "import OCP" 2>/dev/null; then
    ok "cadquery-ocp-novtk installed"
else
    info "Installing cadquery-ocp-novtk (large download, may take a while)..."
    if pip install cadquery-ocp-novtk 2>/dev/null; then
        ok "cadquery-ocp-novtk installed"
    else
        warn "cadquery-ocp-novtk install failed — CAD parsing will be unavailable"
    fi
fi

# ── Phase 4: Frontend dependencies ────────────────────────────────────────────
header "Checking frontend dependencies"

if [[ -d "$SCRIPT_DIR/frontend/node_modules" ]]; then
    ok "node_modules found"
else
    info "Running npm install..."
    (cd "$SCRIPT_DIR/frontend" && npm install) || die "npm install failed"
    ok "npm install complete"
fi

# ── Phase 5: Required directories ─────────────────────────────────────────────
header "Ensuring required directories"

mkdir -p "$SCRIPT_DIR"/{data/{meshes,demos,policies,analytics},configs/{assemblies,arms,calibration},logs}
ok "All directories exist"

# ── Phase 6: Kill stale processes ──────────────────────────────────────────────
header "Cleaning up stale processes"

kill_port() {
    local port=$1
    local pids
    pids=$(ss -tlnp "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u) || true
    if [[ -n "$pids" ]]; then
        for pid in $pids; do
            local pgid
            pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ') || true
            if [[ -n "$pgid" && "$pgid" != "0" ]]; then
                kill -- -"$pgid" 2>/dev/null || true
            else
                kill "$pid" 2>/dev/null || true
            fi
        done
        sleep 1
        # SIGKILL stragglers
        for pid in $pids; do
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
        done
        ok "Killed stale process(es) on port $port"
    else
        ok "Port $port is free"
    fi
}

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

# ── Phase 7: Start backend ────────────────────────────────────────────────────
header "Starting backend (port $BACKEND_PORT)"

export PYTHONPATH="$SCRIPT_DIR/lerobot/src:$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

info "Launching uvicorn..."
python -m uvicorn nextis.api.app:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    --reload \
    > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

sleep 1
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    fail "Backend crashed on startup. Log:"
    tail -20 "$LOG_DIR/backend.log" 2>/dev/null || true
    die "See $LOG_DIR/backend.log for details"
fi

info "Waiting for health check (timeout: ${HEALTH_TIMEOUT}s)..."
elapsed=0
while (( elapsed < HEALTH_TIMEOUT )); do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
        ok "Backend healthy (${elapsed}s)"
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        fail "Backend died during startup. Log:"
        tail -20 "$LOG_DIR/backend.log" 2>/dev/null || true
        die "See $LOG_DIR/backend.log for details"
    fi
    sleep 1
    (( elapsed++ )) || true
done

if (( elapsed >= HEALTH_TIMEOUT )); then
    fail "Health check timed out after ${HEALTH_TIMEOUT}s. Log:"
    tail -20 "$LOG_DIR/backend.log" 2>/dev/null || true
    die "See $LOG_DIR/backend.log for details"
fi

# ── Phase 8: Start frontend ───────────────────────────────────────────────────
header "Starting frontend (port $FRONTEND_PORT)"

export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:$BACKEND_PORT}"
export NEXT_PUBLIC_WS_URL="${NEXT_PUBLIC_WS_URL:-ws://localhost:$BACKEND_PORT/execution/ws}"

info "Launching Next.js dev server..."
(cd "$SCRIPT_DIR/frontend" && npm run dev) \
    > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

sleep 2
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "Frontend crashed on startup. Log:"
    tail -20 "$LOG_DIR/frontend.log" 2>/dev/null || true
    die "See $LOG_DIR/frontend.log for details"
fi

info "Waiting for frontend to compile (timeout: ${FRONTEND_TIMEOUT}s)..."
elapsed=0
while (( elapsed < FRONTEND_TIMEOUT )); do
    if curl -sf "http://localhost:${FRONTEND_PORT}" >/dev/null 2>&1; then
        ok "Frontend ready (${elapsed}s)"
        break
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        fail "Frontend died during startup. Log:"
        tail -20 "$LOG_DIR/frontend.log" 2>/dev/null || true
        die "See $LOG_DIR/frontend.log for details"
    fi
    sleep 1
    (( elapsed++ )) || true
done

if (( elapsed >= FRONTEND_TIMEOUT )); then
    warn "Frontend not responding yet (may still be compiling)"
    warn "Check $LOG_DIR/frontend.log"
fi

# ── Phase 9: Ready ────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}============================================${NC}"
echo -e "${GREEN}${BOLD}           AURA is running${NC}"
echo -e "${GREEN}${BOLD}============================================${NC}"
echo ""
echo -e "  Backend:   ${BOLD}http://localhost:${BACKEND_PORT}${NC}"
echo -e "  Frontend:  ${BOLD}http://localhost:${FRONTEND_PORT}${NC}"
echo -e "  Health:    ${BOLD}${HEALTH_URL}${NC}"
echo ""
echo -e "  Logs:  $LOG_DIR/backend.log"
echo -e "         $LOG_DIR/frontend.log"
echo ""
echo -e "  Press ${BOLD}Ctrl+C${NC} to stop"
echo ""

wait
