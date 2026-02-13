"use client";

interface Capability {
  title: string;
  description: string;
}

const CAPABILITIES: Capability[] = [
  {
    title: "CAD Processing",
    description:
      "Upload STEP files. The system extracts parts, detects contacts, generates assembly meshes, and builds a full parts graph \u2014 automatically.",
  },
  {
    title: "Assembly Planning",
    description:
      "Automatic sequence generation from part geometry. Primitives handle simple steps; complex steps get flagged for human teaching.",
  },
  {
    title: "Force-Feedback Teaching",
    description:
      "Demonstrate assembly steps with haptic teleoperation. The leader arm mirrors the follower with gravity compensation and force reflection.",
  },
  {
    title: "Per-Step Learning",
    description:
      "Each assembly step gets its own learned policy. Ten demonstrations, five minutes of fine-tuning. No reward engineering needed.",
  },
  {
    title: "Autonomous Execution",
    description:
      "State machine walks the assembly graph. Retries on failure, escalates to human, tracks success rates \u2014 step by step.",
  },
  {
    title: "Real-Time Analytics",
    description:
      "Per-step metrics: success rates, cycle times, demo counts. All indexed by the assembly graph for full traceability.",
  },
];

export function ArchitectureGrid() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {CAPABILITIES.map((cap) => (
        <div
          key={cap.title}
          className="rounded-xl border border-bg-tertiary bg-bg-elevated p-5"
        >
          <p className="text-[14px] font-semibold text-text-primary">
            {cap.title}
          </p>
          <p className="mt-2 text-[13px] leading-relaxed text-text-secondary">
            {cap.description}
          </p>
        </div>
      ))}
    </div>
  );
}
