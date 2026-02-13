// ---------------------------------------------------------------------------
// Documentation content — typed data, no MDX or markdown parser needed
// ---------------------------------------------------------------------------

// --- Rich text types ---

export interface TextRun {
  text: string;
  code?: boolean;
  bold?: boolean;
  link?: { href: string; external?: boolean };
}

export type RichText = string | TextRun | (string | TextRun)[];

// --- Content block types ---

export interface ParagraphBlock {
  type: "paragraph";
  content: RichText;
}

export interface CodeBlock {
  type: "code";
  language: string;
  content: string;
}

export interface TableBlock {
  type: "table";
  headers: string[];
  rows: string[][];
}

export interface ListBlock {
  type: "list";
  ordered?: boolean;
  items: RichText[];
}

export interface HeadingBlock {
  type: "heading";
  level: 3 | 4;
  text: string;
}

export interface CalloutBlock {
  type: "callout";
  variant: "info" | "warning";
  content: RichText;
}

export type ContentBlock =
  | ParagraphBlock
  | CodeBlock
  | TableBlock
  | ListBlock
  | HeadingBlock
  | CalloutBlock;

// --- Document structure ---

export interface DocSubsection {
  id: string;
  title: string;
  blocks: ContentBlock[];
}

export interface DocSection {
  id: string;
  title: string;
  subsections: DocSubsection[];
}

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------

export const DOCS_CONTENT: DocSection[] = [
  // =========================================================================
  // GETTING STARTED
  // =========================================================================
  {
    id: "getting-started",
    title: "Getting Started",
    subsections: [
      {
        id: "quick-start",
        title: "Quick Start",
        blocks: [
          {
            type: "paragraph",
            content: "Get the AURA platform running locally in under five minutes.",
          },
          { type: "heading", level: 3, text: "Backend" },
          {
            type: "code",
            language: "bash",
            content: `conda activate nextis
pip install -e ".[dev]"
python scripts/demo.py`,
          },
          { type: "heading", level: 3, text: "Frontend (separate terminal)" },
          {
            type: "code",
            language: "bash",
            content: `cd frontend
npm install
npm run dev`,
          },
          {
            type: "paragraph",
            content: [
              "Open ",
              { text: "http://localhost:3000", code: true },
              ". Press ",
              { text: "Space", bold: true },
              " to start the 57-step gearbox assembly with stub primitives and real-time WebSocket updates.",
            ],
          },
          { type: "heading", level: 3, text: "Keyboard Shortcuts" },
          {
            type: "table",
            headers: ["Key", "Action"],
            rows: [
              ["Space", "Play / Pause assembly"],
              ["Escape", "Stop execution"],
              ["↑ / ↓", "Navigate steps"],
              ["← / →", "Previous / Next step"],
            ],
          },
        ],
      },
      {
        id: "installation",
        title: "Installation",
        blocks: [
          { type: "heading", level: 3, text: "System Requirements" },
          {
            type: "list",
            items: [
              [{ text: "Python 3.11+", bold: true }, " (via conda or pyenv)"],
              [{ text: "Node.js 18+", bold: true }, " and npm"],
              [{ text: "conda", bold: true }, " (Miniconda or Anaconda)"],
            ],
          },
          { type: "heading", level: 3, text: "Python Environment" },
          {
            type: "code",
            language: "bash",
            content: `conda create -n nextis python=3.11 -y
conda activate nextis
pip install -e ".[dev]"`,
          },
          { type: "heading", level: 3, text: "CAD Parsing (Optional)" },
          {
            type: "paragraph",
            content: [
              "For STEP file parsing, install ",
              { text: "cadquery-ocp-novtk", code: true },
              " via pip. Do not use conda — the solver is unusably slow.",
            ],
          },
          {
            type: "code",
            language: "bash",
            content: "pip install cadquery-ocp-novtk",
          },
          { type: "heading", level: 3, text: "Frontend" },
          {
            type: "code",
            language: "bash",
            content: `cd frontend
npm install`,
          },
          {
            type: "callout",
            variant: "info",
            content: [
              "The frontend uses Next.js 16 with React 19 and Tailwind v4. No additional ",
              "configuration is needed — ",
              { text: "npm run dev", code: true },
              " starts the dev server on port 3000.",
            ],
          },
        ],
      },
      {
        id: "first-assembly",
        title: "First Assembly",
        blocks: [
          {
            type: "paragraph",
            content:
              "AURA ships with two pre-configured assemblies. The gearbox assembly (57 steps, 44 parts) is the default and demonstrates the full execution pipeline.",
          },
          { type: "heading", level: 3, text: "Assembly Graph Structure" },
          {
            type: "paragraph",
            content: "Every assembly is described by a JSON graph with these top-level fields:",
          },
          {
            type: "table",
            headers: ["Field", "Type", "Description"],
            rows: [
              ["id", "string", "Unique identifier (e.g. assem_gearbox)"],
              ["name", "string", "Display name"],
              ["parts", "Record<string, Part>", "Part catalog keyed by part ID"],
              ["steps", "Record<string, AssemblyStep>", "Step definitions keyed by step ID"],
              ["stepOrder", "string[]", "Topologically sorted execution order"],
            ],
          },
          {
            type: "paragraph",
            content: [
              "Assembly configs live at ",
              { text: "configs/assemblies/", code: true },
              ". Open ",
              { text: "assem_gearbox.json", code: true },
              " to see the full gearbox definition.",
            ],
          },
        ],
      },
    ],
  },

  // =========================================================================
  // GUIDES
  // =========================================================================
  {
    id: "guides",
    title: "Guides",
    subsections: [
      {
        id: "uploading-cad",
        title: "Uploading CAD Files",
        blocks: [
          {
            type: "paragraph",
            content: [
              "Upload a STEP file via ",
              { text: "POST /assemblies/upload", code: true },
              " or the upload button in the dashboard. The parser extracts parts, detects contact surfaces, generates GLB meshes, and builds the assembly graph.",
            ],
          },
          { type: "heading", level: 3, text: "Supported Formats" },
          {
            type: "list",
            items: [
              [{ text: ".step", code: true }, " / ", { text: ".stp", code: true }, " — STEP AP214 / AP203"],
            ],
          },
          { type: "heading", level: 3, text: "What the Parser Does" },
          {
            type: "list",
            ordered: true,
            items: [
              "Imports STEP file using OCC (cadquery-ocp-novtk)",
              "Traverses the XDE assembly tree to extract individual parts",
              "Classifies part geometry (box, cylinder, sphere) from bounding boxes",
              "Detects inter-part contact faces using BRepExtrema distance analysis",
              "Tessellates each part and exports GLB meshes",
              "Builds a sequenced assembly plan with heuristic ordering",
            ],
          },
          {
            type: "paragraph",
            content: [
              "Meshes are saved to ",
              { text: "data/meshes/{assembly_id}/{part_id}.glb", code: true },
              " and served as static files at ",
              { text: "/meshes/", code: true },
              ".",
            ],
          },
        ],
      },
      {
        id: "teaching-steps",
        title: "Teaching Steps",
        blocks: [
          {
            type: "paragraph",
            content:
              "Complex assembly steps (press fits, insertions, screwing) require human demonstrations. The teaching workflow records force-feedback teleoperation as HDF5 datasets.",
          },
          { type: "heading", level: 3, text: "Recording Workflow" },
          {
            type: "list",
            ordered: true,
            items: [
              "Select the step you want to teach in the step list",
              [
                "Start teleoperation: ",
                { text: "POST /teleop/start?mock=true", code: true },
              ],
              [
                "Begin recording: ",
                { text: "POST /recording/step/{step_id}/start", code: true },
              ],
              "Demonstrate the step using the leader arm (or keyboard in mock mode)",
              [
                "Stop recording: ",
                { text: "POST /recording/stop", code: true },
              ],
            ],
          },
          {
            type: "paragraph",
            content: [
              "Demos are stored as HDF5 files at ",
              { text: "data/demos/{assembly_id}/{step_id}/", code: true },
              ". Each file contains joint positions, gripper state, and actions sampled at 50 Hz.",
            ],
          },
          {
            type: "callout",
            variant: "info",
            content:
              "A minimum of 10 demonstrations is recommended for reliable policy training. Each demo typically takes 2\u20135 minutes.",
          },
        ],
      },
      {
        id: "training-policies",
        title: "Training Policies",
        blocks: [
          {
            type: "paragraph",
            content:
              "After collecting demonstrations, train a per-step behavioral cloning policy. AURA supports ACT (Action Chunking with Transformers) architecture via LeRobot.",
          },
          {
            type: "code",
            language: "bash",
            content: `# Launch training for a specific step
curl -X POST http://localhost:8000/training/step/step_001/train \\
  -H "Content-Type: application/json" \\
  -d '{"assemblyId": "assem_gearbox", "architecture": "act", "numSteps": 10000}'`,
          },
          {
            type: "paragraph",
            content: [
              "Checkpoints are saved to ",
              { text: "data/policies/{assembly_id}/{step_id}/policy.pt", code: true },
              ". Poll job status with ",
              { text: "GET /training/jobs/{job_id}", code: true },
              ".",
            ],
          },
          {
            type: "callout",
            variant: "warning",
            content:
              "Training routes are currently stubbed — the endpoint accepts requests and tracks job state in memory, but does not run actual training yet.",
          },
        ],
      },
      {
        id: "running-assemblies",
        title: "Running Assemblies",
        blocks: [
          {
            type: "paragraph",
            content:
              "The execution sequencer walks the assembly graph step by step, dispatching each to a motion primitive or learned policy.",
          },
          {
            type: "code",
            language: "bash",
            content: `curl -X POST http://localhost:8000/execution/start \\
  -H "Content-Type: application/json" \\
  -d '{"assemblyId": "assem_gearbox", "speed": 1.0}'`,
          },
          { type: "heading", level: 3, text: "Execution States" },
          {
            type: "table",
            headers: ["Phase", "Description"],
            rows: [
              ["idle", "No assembly running"],
              ["running", "Stepping through the graph"],
              ["paused", "Execution paused, resumable"],
              ["teaching", "Waiting for human to complete a step"],
              ["complete", "All steps finished"],
              ["error", "Critical failure occurred"],
            ],
          },
          { type: "heading", level: 3, text: "Retry & Escalation" },
          {
            type: "paragraph",
            content: [
              "Each step allows up to ",
              { text: "maxRetries + 1", code: true },
              " attempts (default 3 retries = 4 total). After all retries are exhausted, the sequencer enters ",
              { text: "teaching", code: true },
              " state and waits for a human operator to intervene via ",
              { text: "POST /execution/intervene", code: true },
              ".",
            ],
          },
          {
            type: "paragraph",
            content: [
              "Connect to ",
              { text: "ws://localhost:8000/execution/ws", code: true },
              " for real-time state updates broadcast as JSON.",
            ],
          },
        ],
      },
    ],
  },

  // =========================================================================
  // API REFERENCE
  // =========================================================================
  {
    id: "api-reference",
    title: "API Reference",
    subsections: [
      {
        id: "api-assembly",
        title: "Assembly (/assemblies)",
        blocks: [
          {
            type: "table",
            headers: ["Method", "Path", "Description"],
            rows: [
              ["GET", "/assemblies", "List all assemblies (id + name)"],
              ["GET", "/assemblies/{id}", "Full assembly graph"],
              ["POST", "/assemblies", "Create assembly from JSON body"],
              ["PATCH", "/assemblies/{id}/steps/{step_id}", "Partially update a step"],
              ["DELETE", "/assemblies/{id}", "Delete assembly and meshes"],
              ["POST", "/assemblies/upload", "Upload .step/.stp \u2192 parse \u2192 assembly"],
              ["POST", "/assemblies/{id}/analyze", "AI analysis (query: apply=bool)"],
            ],
          },
          {
            type: "paragraph",
            content: [
              "The upload endpoint accepts ",
              { text: "multipart/form-data", code: true },
              " with a ",
              { text: "file", code: true },
              " field. Returns the full ",
              { text: "AssemblyGraph", code: true },
              " with generated parts, steps, and GLB mesh paths.",
            ],
          },
        ],
      },
      {
        id: "api-execution",
        title: "Execution (/execution)",
        blocks: [
          {
            type: "table",
            headers: ["Method", "Path", "Description"],
            rows: [
              ["GET", "/execution/state", "Current sequencer state snapshot"],
              ["POST", "/execution/start", "Begin execution (body: assemblyId, speed)"],
              ["POST", "/execution/pause", "Pause current execution"],
              ["POST", "/execution/resume", "Resume from pause"],
              ["POST", "/execution/stop", "Stop and reset to idle"],
              ["POST", "/execution/intervene", "Signal human completed current step"],
              ["WS", "/execution/ws", "Real-time state broadcast"],
            ],
          },
          {
            type: "paragraph",
            content: [
              "The ",
              { text: "start", code: true },
              " endpoint accepts a JSON body with ",
              { text: "assemblyId: string", code: true },
              " and optional ",
              { text: "speed: float", code: true },
              " (0.1\u201320.0, default 1.0). The WebSocket broadcasts the full ",
              { text: "ExecutionState", code: true },
              " object on every state change.",
            ],
          },
        ],
      },
      {
        id: "api-recording",
        title: "Recording (/recording)",
        blocks: [
          {
            type: "table",
            headers: ["Method", "Path", "Description"],
            rows: [
              ["POST", "/recording/step/{step_id}/start", "Start recording (body: assemblyId)"],
              ["POST", "/recording/stop", "Stop recording, flush to HDF5"],
              ["POST", "/recording/discard", "Abandon active recording"],
              ["GET", "/recording/demos/{assembly_id}/{step_id}", "List recorded demos"],
              ["POST", "/recording/demos/{a_id}/{s_id}/{d_id}/delete", "Delete a demo"],
            ],
          },
          {
            type: "paragraph",
            content: [
              "Recordings capture joint positions, gripper state, force/torque, and actions at ",
              { text: "50 Hz", bold: true },
              " into HDF5 files at ",
              { text: "data/demos/{assembly_id}/{step_id}/", code: true },
              ".",
            ],
          },
        ],
      },
      {
        id: "api-training",
        title: "Training (/training)",
        blocks: [
          {
            type: "table",
            headers: ["Method", "Path", "Description"],
            rows: [
              ["POST", "/training/step/{step_id}/train", "Launch training (body: assemblyId, architecture, numSteps)"],
              ["GET", "/training/jobs/{job_id}", "Job status (pending/running/completed/failed)"],
              ["GET", "/training/jobs", "List all training jobs"],
            ],
          },
          {
            type: "callout",
            variant: "warning",
            content:
              "Training routes are currently stubbed. The API accepts requests and tracks job state in memory, but does not execute actual model training.",
          },
        ],
      },
      {
        id: "api-analytics",
        title: "Analytics (/analytics)",
        blocks: [
          {
            type: "table",
            headers: ["Method", "Path", "Description"],
            rows: [
              ["GET", "/analytics/{assembly_id}/steps", "Per-step metrics for entire assembly"],
            ],
          },
          {
            type: "paragraph",
            content:
              "Returns an array of step metrics including success rate, average duration, total attempts, demo count, and recent run history. Metrics are stored as JSON at data/analytics/{assembly_id}.json.",
          },
        ],
      },
    ],
  },

  // =========================================================================
  // HARDWARE
  // =========================================================================
  {
    id: "hardware",
    title: "Hardware",
    subsections: [
      {
        id: "arm-setup",
        title: "Arm Setup",
        blocks: [
          { type: "heading", level: 3, text: "Follower Arms (Damiao)" },
          {
            type: "paragraph",
            content:
              "The follower arms are Damiao Aira Zero with 7 DOF. Three motor types are used across the kinematic chain:",
          },
          {
            type: "table",
            headers: ["Joint", "Motor", "kp", "kd"],
            rows: [
              ["Shoulder (J1\u2013J3)", "J8009P", "30", "1.5"],
              ["Elbow (J4\u2013J5)", "J4340P", "30", "1.5"],
              ["Wrist (J6\u2013J7)", "J4310", "15", "0.25"],
            ],
          },
          { type: "heading", level: 3, text: "Leader Arms (Dynamixel)" },
          {
            type: "paragraph",
            content: [
              "Leader arms use Dynamixel XL330-M077 and XL330-M288 servos connected via USB serial. ",
              "Force feedback maps follower gripper torque to leader ",
              { text: "Goal_Current", code: true },
              " ceiling and joint error to ",
              { text: "CURRENT_POSITION", code: true },
              " mode.",
            ],
          },
          {
            type: "paragraph",
            content: [
              "Arm definitions are stored as YAML in ",
              { text: "configs/arms/", code: true },
              ". Each definition includes motor type, serial port, and calibration status.",
            ],
          },
        ],
      },
      {
        id: "calibration",
        title: "Calibration",
        blocks: [
          {
            type: "paragraph",
            content: [
              "Calibration profiles live at ",
              { text: "configs/calibration/{arm_id}/", code: true },
              " and contain four JSON files:",
            ],
          },
          {
            type: "table",
            headers: ["File", "Purpose"],
            rows: [
              ["zeros.json", "Joint zero-position offsets"],
              ["ranges.json", "Joint angle limits (min/max)"],
              ["inversions.json", "Motor direction inversions per joint"],
              ["gravity.json", "Gravity compensation parameters"],
            ],
          },
          {
            type: "callout",
            variant: "info",
            content:
              "Calibration profiles are not yet populated. The calibration system is planned but not yet implemented.",
          },
        ],
      },
      {
        id: "can-config",
        title: "CAN Configuration",
        blocks: [
          {
            type: "paragraph",
            content: [
              "Damiao motors communicate over CAN bus. AURA uses SocketCAN (",
              { text: "can0", code: true },
              ") or a USB-CAN serial bridge.",
            ],
          },
          { type: "heading", level: 3, text: "SocketCAN Setup" },
          {
            type: "code",
            language: "bash",
            content: `sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up`,
          },
          { type: "heading", level: 3, text: "MIT Impedance Control" },
          {
            type: "paragraph",
            content: [
              "All Damiao motors run in MIT impedance mode with per-joint ",
              { text: "kp", code: true },
              " (stiffness) and ",
              { text: "kd", code: true },
              " (damping) parameters. The control loop runs at ",
              { text: "60 Hz", bold: true },
              " (16.67 ms). Never block the control loop for I/O.",
            ],
          },
        ],
      },
    ],
  },

  // =========================================================================
  // ARCHITECTURE
  // =========================================================================
  {
    id: "architecture",
    title: "Architecture",
    subsections: [
      {
        id: "system-overview",
        title: "System Overview",
        blocks: [
          {
            type: "paragraph",
            content:
              "AURA follows a layered architecture. No layer reaches down more than one level. The execution layer uses control but never hardware directly.",
          },
          {
            type: "code",
            language: "",
            content: `hardware/ \u2192 control/ \u2192 execution/
assembly/ \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2192 api/ \u2192 frontend/
learning/recorder    \u2190 api/routes/recording
learning/rl_trainer  \u2192 learning/sac, replay_buffer, reward
execution/policy_router \u2192 learning/policy_loader
analytics/store      \u2190 api/routes/{analytics, execution}`,
          },
          { type: "heading", level: 3, text: "Key Principles" },
          {
            type: "list",
            items: [
              "Assembly graph is the central data model \u2014 everything indexes by step_id",
              "Recording, training, execution, and analytics are all per-step",
              "Filesystem-backed storage: YAML + JSON + HDF5 (no database)",
              "Mock mode for hardware-free development and testing",
            ],
          },
        ],
      },
      {
        id: "assembly-graph",
        title: "Assembly Graph",
        blocks: [
          {
            type: "paragraph",
            content: [
              "The ",
              { text: "AssemblyGraph", code: true },
              " model (defined in ",
              { text: "nextis/assembly/models.py", code: true },
              ") is the central data structure.",
            ],
          },
          { type: "heading", level: 3, text: "AssemblyStep Fields" },
          {
            type: "table",
            headers: ["Field", "Type", "Description"],
            rows: [
              ["id", "string", "Unique step identifier (e.g. step_001)"],
              ["name", "string", "Human-readable name"],
              ["partIds", "string[]", "Parts involved in this step"],
              ["dependencies", "string[]", "Step IDs that must complete first"],
              ["handler", "string", "primitive | policy | rl_finetune"],
              ["primitiveType", "string?", "move_to, pick, place, guarded_move, linear_insert, screw, press_fit"],
              ["primitiveParams", "object?", "Handler-specific parameters"],
              ["policyId", "string?", "Trained policy checkpoint path"],
              ["successCriteria", "object", "Completion condition (type + threshold)"],
              ["maxRetries", "number", "Max retry attempts (default 3)"],
            ],
          },
        ],
      },
      {
        id: "policy-router",
        title: "Policy Router",
        blocks: [
          {
            type: "paragraph",
            content: [
              "The policy router (",
              { text: "nextis/execution/policy_router.py", code: true },
              ") dispatches each step based on its ",
              { text: "handler", code: true },
              " field:",
            ],
          },
          {
            type: "table",
            headers: ["Handler", "Action", "Checkpoint Path"],
            rows: [
              ["primitive", "Runs PrimitiveLibrary.run() (currently stubbed)", "\u2014"],
              ["policy", "Loads BC checkpoint, runs 50 Hz inference", "data/policies/{a_id}/{s_id}/policy.pt"],
              ["rl_finetune", "Loads RL checkpoint (falls back to BC)", "data/policies/{a_id}/{s_id}/policy_rl.pt"],
            ],
          },
          {
            type: "paragraph",
            content:
              "If a policy checkpoint is missing, the router returns a failure result which triggers the retry/escalation logic in the sequencer.",
          },
        ],
      },
      {
        id: "state-machine",
        title: "State Machine",
        blocks: [
          {
            type: "paragraph",
            content: [
              "The execution sequencer (",
              { text: "nextis/execution/sequencer.py", code: true },
              ") implements a state machine that walks the assembly graph:",
            ],
          },
          {
            type: "code",
            language: "",
            content: `IDLE
\u251C\u2500> RUNNING \u2500> STEP_ACTIVE
\u2502        \u251C\u2500> STEP_COMPLETE (continue to next)
\u2502        \u251C\u2500> PAUSED (resume \u2192 STEP_ACTIVE)
\u2502        \u2514\u2500> WAITING_FOR_HUMAN (intervene \u2192 continue)
\u251C\u2500> COMPLETE (all steps done)
\u2514\u2500> ERROR (critical failure)`,
          },
          { type: "heading", level: 3, text: "Per-Step Execution Loop" },
          {
            type: "list",
            ordered: true,
            items: [
              "Step state transitions from pending to running",
              "Dispatch to policy router (primitive, BC policy, or RL policy)",
              "On success: mark as complete, advance to next step",
              ["On failure: retry up to ", { text: "maxRetries", code: true }, " times with 0.5s backoff"],
              "After all retries exhausted: enter WAITING_FOR_HUMAN state",
              "Human operator intervenes via POST /execution/intervene",
              "After final step: transition to COMPLETE",
            ],
          },
        ],
      },
    ],
  },
];
