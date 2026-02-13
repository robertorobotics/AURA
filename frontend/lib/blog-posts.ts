export interface BlogPost {
  slug: string;
  title: string;
  date: string;
  summary: string;
  tags: string[];
  content: string;
}

export const blogPosts: BlogPost[] = [
  {
    slug: "assembly-graph",
    title: "How AURA's Assembly Graph Works",
    date: "2025-02-01",
    summary:
      "The assembly graph is the central data model in AURA. Every recording, execution run, trained policy, and analytics metric is indexed by step ID.",
    tags: ["architecture", "assembly"],
    content: `AURA's core abstraction is the assembly graph — a directed acyclic graph where nodes are assembly steps and edges are dependencies. Every part of the system, from recording demonstrations to running learned policies to collecting analytics, indexes into this graph by step ID. If a piece of code doesn't reference a step, it probably doesn't belong in the platform.

The graph is defined using two Pydantic models in nextis/assembly/models.py. An AssemblyGraph contains a parts dictionary (mapping part IDs to geometry and mesh paths), a steps dictionary (mapping step IDs to AssemblyStep objects), and a topologically sorted step_order list. Each AssemblyStep specifies which parts are involved, which steps must complete first (dependencies), what handler to use (primitive, policy, or rl_finetune), and what constitutes success. This explicit structure means the sequencer never has to guess what comes next — it just walks the ordered list and checks dependency satisfaction.

The graph is generated automatically from CAD files. When you upload a STEP file, the cad_parser module traverses the XDE document tree, extracts every part with its geometry, detects contact surfaces between parts using bounding box proximity and face-to-face distance checks, and exports GLB meshes for the 3D viewer. The sequence_planner then takes these parts and contacts and produces a feasible assembly order using heuristics: larger parts that form the base go first, smaller parts that attach to existing subassemblies come later, and the type of contact (surface vs. cylindrical vs. threaded) determines whether a step gets assigned pick, place, press_fit, or linear_insert as its primitive type.

The execution engine in nextis/execution/sequencer.py is a state machine that walks the graph step by step. For each step, it checks that all dependencies are satisfied, then dispatches to the appropriate handler via the policy_router. If a step fails, the sequencer retries up to the configured max_retries. If retries are exhausted, it escalates — pausing execution and signaling for human intervention. The entire state is broadcast over WebSocket so the frontend can show real-time progress through the graph.

This architecture makes the system modular in a practical way. You can teach one step by demonstration, assign another to a motion primitive, and fine-tune a third with reinforcement learning — all within the same assembly. Adding a new step type or swapping a policy doesn't require changing the sequencer or the graph structure. The assembly graph is the contract between components, and as long as everyone speaks step IDs, the system stays coherent.`,
  },
  {
    slug: "force-feedback-teleoperation",
    title: "Force Feedback Teleoperation for Assembly Teaching",
    date: "2025-01-20",
    summary:
      "Force feedback turns teleoperation from remote joysticking into something that feels like holding the part yourself. Here's how AURA's leader-follower system works.",
    tags: ["control", "teleoperation", "hardware"],
    content: `Assembly is a contact-rich task. When you press-fit a bearing into a housing, you need to feel the moment it seats. When you thread a screw, you need to feel the engagement point. Without force feedback, teleoperation is just remote joysticking — the operator watches and guesses. With it, they feel the physics of the task through their hands, and the demonstrations they record are dramatically better because of it.

AURA uses a leader-follower architecture. The leader arms are Dynamixel XL330 servos — small, backdrivable motors that an operator moves by hand. The follower arms are Damiao Aira Zero quasi-direct-drive actuators — J8009P for the shoulder, J4340P for the elbow, J4310 for the wrist — running MIT-mode impedance control over CAN bus. The control loop runs at 60 Hz. Each cycle, the leader's joint positions are read, mapped through the joint_mapping module (which handles the Dynamixel-to-Damiao coordinate conversion, gear ratios, and direction inversions), and sent as position targets to the follower.

The force feedback path flows in reverse. The follower arm's torque sensors measure the forces encountered during contact. These torque readings are processed by the force_feedback module, which implements two mechanisms. For the gripper, an exponential moving average (EMA) filter smooths the raw torque signal and maps it to a current limit on the leader's gripper servo — so when the follower grips harder, the operator feels proportional resistance. For the arm joints, a virtual spring model converts follower torque errors into position offsets on the leader, creating a sensation of stiffness when the follower encounters obstacles.

The leader_assist module adds gravity compensation, friction assist, and configurable damping on top of the force feedback. Gravity compensation subtracts the estimated gravitational torque from each joint so the leader arm feels weightless — the operator only feels task forces, not the weight of the leader hardware. Friction assist adds a small torque in the direction of motion to overcome the leader's own static friction. Together, these make the leader feel transparent: the operator's hand moves, the follower copies, and forces flow back naturally.

The 60 Hz loop is managed by teleop_loop.py, which coordinates leader reading, joint mapping, follower commanding, force feedback computation, safety monitoring, and intervention detection in a single tight cycle. The loop never blocks on I/O — camera frames are handled asynchronously with zero-order hold, and recording runs on a separate 50 Hz thread. If any safety limit is exceeded (joint torque, load cell, velocity), the safety module triggers an emergency stop within one control cycle. This architecture ensures that force feedback is responsive enough to be useful — at 60 Hz, the round-trip latency from contact to haptic sensation is under 17 milliseconds.`,
  },
  {
    slug: "per-step-learning",
    title: "From Demos to Policies: Per-Step Learning in AURA",
    date: "2025-01-10",
    summary:
      "AURA trains a separate policy for each assembly step rather than one monolithic policy for the whole task. Here's why that works better and how the learning pipeline is structured.",
    tags: ["learning", "policies", "HIL-SERL"],
    content: `Most robot learning research trains a single policy for an entire task. For assembly, this is a bad idea. A gearbox has 57 steps — some are simple pick-and-place operations, others are delicate press fits requiring sub-millimeter precision. Training one policy to handle all of them requires enormous amounts of data, and a failure in step 42 means you might need to retrain the whole thing. AURA takes a different approach: one policy per step, trained independently, composed by the execution graph.

The pipeline starts with demonstration recording. An operator performs a step using the force-feedback leader arm while the recorder module captures joint positions, velocities, torques, gripper state, and (eventually) camera frames at 50 Hz into HDF5 files. Each recording is tagged with the assembly ID and step ID, so the system knows exactly which step this demo belongs to. Ten demonstrations of a five-minute step typically provide enough coverage for behavior cloning.

From demonstrations, we train behavior cloning (BC) policies using architectures like ACT or Diffusion Policy through the LeRobot framework. The key insight is that each step has a clear start state (the output of the previous step) and a clear success criterion (defined in the assembly graph). This means BC training for each step is a well-scoped supervised learning problem — small dataset, clear objective, fast iteration. A policy checkpoint is saved per step at data/policies/{assembly_id}/{step_id}/policy.pt.

Behavior cloning gets you 80% of the way there, but the last 20% — the contact-rich parts where small errors compound — often needs reinforcement learning. AURA uses HIL-SERL (Human-in-the-Loop Sample-Efficient Reinforcement Learning) for fine-tuning. The rl_trainer module runs an online RL loop where the BC policy executes the step, a human operator can intervene at any time to correct mistakes, and both autonomous and intervention trajectories are stored in a replay buffer. The SAC (Soft Actor-Critic) algorithm trains on this mixed buffer using the RLPD (Reinforcement Learning with Prior Data) approach — treating the BC demonstrations and human corrections as prior data alongside the online experience.

The reward signal comes from the reward module, which combines dense rewards (progress toward the step's success criteria, measured by the StepVerifier) with sparse rewards (binary success/failure at step completion). Human interventions are particularly valuable: they demonstrate exactly what to do in the states where the BC policy fails, providing targeted training signal in the most important parts of the state space. After fine-tuning, the RL checkpoint is saved alongside the BC checkpoint, and the policy_router in the execution engine automatically prefers the RL-refined version when it exists.`,
  },
];

export function getPostBySlug(slug: string): BlogPost | undefined {
  return blogPosts.find((p) => p.slug === slug);
}
