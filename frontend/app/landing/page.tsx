"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useAssembly } from "@/context/AssemblyContext";

const LandingViewer = dynamic(
  () =>
    import("@/components/landing/LandingViewer").then((m) => ({
      default: m.LandingViewer,
    })),
  { ssr: false },
);

const STATS = [
  { value: "57 steps", desc: "Gearbox assembly, fully autonomous" },
  { value: "1\u20132 days", desc: "Setup time per new product" },
  { value: "< 5 min", desc: "Per teaching demonstration" },
  { value: "93%", desc: "First-run success rate" },
];

const PIPELINE = [
  {
    title: "Parse",
    body: "Upload a STEP file. AURA extracts every part, contact surface, and geometric constraint. Your CAD becomes an assembly graph in seconds.",
  },
  {
    title: "Plan",
    body: "Assembly sequence is generated from contact analysis. Easy steps get motion primitives. Hard steps get teaching slots. You review and adjust.",
  },
  {
    title: "Teach",
    body: "Demonstrate difficult steps through force-feedback teleoperation. The robot feels what you feel. Ten demonstrations per step is typically enough.",
  },
  {
    title: "Run",
    body: "The robot executes the full assembly autonomously. Per-step policies handle the hard parts. If something fails, it retries \u2014 then asks you.",
  },
];

const TECH_CARDS = [
  { title: "Assembly", desc: "STEP parsing, contact analysis, assembly graph generation, GLB mesh export" },
  { title: "Control", desc: "60Hz teleoperation, force feedback, safety monitoring, seven motion primitives" },
  { title: "Learning", desc: "Per-step demo recording, behavior cloning, SAC, HIL-SERL fine-tuning" },
  { title: "Execution", desc: "State machine sequencer with retry, pause/resume, human-in-the-loop escalation" },
  { title: "Perception", desc: "Force/position verification, step completion classifiers, closed-loop feedback" },
  { title: "Hardware", desc: "Damiao quasi-direct-drive arms, Dynamixel leaders, CAN + serial protocols" },
];

export default function LandingPage() {
  const { assembly } = useAssembly();
  const [activeTab, setActiveTab] = useState(0);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("revealed");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15 },
    );
    const elements = document.querySelectorAll(".reveal");
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return (
    <div className="h-screen overflow-y-auto scroll-smooth">
      {/* Nav */}
      <nav className="sticky top-0 z-50 flex h-[52px] items-center justify-between border-b border-bg-tertiary bg-bg-primary/92 px-6 backdrop-blur-lg">
        <div className="flex items-center gap-6">
          <span className="text-[15px] font-extrabold tracking-[0.16em] text-text-primary">AURA</span>
          <a href="#product" className="text-[13px] text-text-secondary hover:text-text-primary">Product</a>
          <a href="#technology" className="text-[13px] text-text-secondary hover:text-text-primary">Technology</a>
          <a href="#about" className="text-[13px] text-text-secondary hover:text-text-primary">About</a>
        </div>
        <a href="/" className="rounded-md bg-accent px-4 py-1.5 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover">
          Open Platform
        </a>
      </nav>

      {/* Hero */}
      <section className="flex min-h-[85vh] items-center px-6 py-16">
        <div className="mx-auto grid max-w-6xl items-center gap-12 md:grid-cols-2">
          <div>
            <span className="text-[11px] uppercase tracking-[0.1em] text-text-tertiary">
              Assembly Automation
            </span>
            <h1 className="mt-4 whitespace-pre-line text-[48px] font-extrabold leading-[1.06] tracking-[-0.03em] text-text-primary">
              {"Upload CAD.\nRobot assembles it."}
            </h1>
            <p className="mt-4 max-w-[400px] text-[16px] leading-[1.65] text-text-secondary">
              AURA turns STEP files into autonomous assembly programs. Parse the geometry,
              plan the sequence, teach the hard steps, run it.
            </p>
            <div className="mt-8 flex items-center gap-4">
              <a href="/" className="rounded-md bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover">
                Try Demo
              </a>
              <a href="#product" className="rounded-md border border-bg-tertiary px-4 py-2 text-[13px] font-medium text-text-secondary transition-colors hover:bg-bg-secondary">
                How It Works &rarr;
              </a>
            </div>
            <p className="mt-3 text-[11px] text-text-tertiary">
              No signup required. Mock hardware in browser.
            </p>
          </div>
          <div className="aspect-[4/3] w-full overflow-hidden rounded-lg bg-bg-viewer">
            {assembly && <LandingViewer assembly={assembly} />}
          </div>
        </div>
      </section>

      {/* Product Metrics */}
      <section className="border-y border-bg-tertiary bg-bg-secondary px-6 py-10">
        <div className="reveal mx-auto flex max-w-5xl items-start justify-center gap-12">
          {STATS.map((s) => (
            <div key={s.value} className="text-center">
              <p className="font-mono text-[20px] font-bold tabular-nums text-text-primary">{s.value}</p>
              <p className="mt-1 max-w-[150px] text-[11px] text-text-tertiary">{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pipeline */}
      <section id="product" className="px-6 py-16 md:py-24">
        <div className="mx-auto max-w-5xl">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">How It Works</p>
          <h2 className="mt-3 text-[28px] font-bold text-text-primary">
            Four steps from CAD to autonomous assembly
          </h2>
          <div className="mt-10 flex gap-8">
            <div className="flex w-[240px] shrink-0 flex-col gap-1">
              {PIPELINE.map((step, i) => (
                <button
                  key={step.title}
                  onClick={() => setActiveTab(i)}
                  className={`flex items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors ${
                    i === activeTab
                      ? "bg-accent-light shadow-[inset_3px_0_0_0_var(--color-text-tertiary)]"
                      : "hover:bg-bg-secondary"
                  }`}
                >
                  <span className="font-mono text-[12px] font-semibold text-text-tertiary">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className={`text-[14px] font-medium ${i === activeTab ? "text-text-primary" : "text-text-secondary"}`}>
                    {step.title}
                  </span>
                </button>
              ))}
            </div>
            <div className="flex-1 rounded-lg border border-bg-tertiary bg-bg-elevated p-6">
              <span className="font-mono text-[11px] text-text-tertiary">
                {String(activeTab + 1).padStart(2, "0")}
              </span>
              <h3 className="mt-1 text-[22px] font-bold text-text-primary">
                {PIPELINE[activeTab]?.title}
              </h3>
              <p className="mt-3 text-[14px] leading-[1.7] text-text-secondary">
                {PIPELINE[activeTab]?.body}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Technology */}
      <section id="technology" className="border-t border-bg-tertiary bg-bg-secondary px-6 py-16 md:py-24">
        <div className="reveal mx-auto max-w-5xl">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">Technology</p>
          <h2 className="mt-3 text-[28px] font-bold text-text-primary">Built for real hardware</h2>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {TECH_CARDS.map((c) => (
              <div key={c.title} className="rounded-lg border border-bg-tertiary bg-bg-elevated p-5">
                <h3 className="text-[13px] font-bold text-text-primary">{c.title}</h3>
                <p className="mt-1.5 text-[12px] leading-[1.6] text-text-secondary">{c.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Vision */}
      <section id="about" className="px-6 py-16 md:py-24">
        <div className="reveal mx-auto max-w-[500px] text-center">
          <p className="text-[20px] font-light italic leading-[1.8] text-text-secondary">
            &ldquo;The personal computer fulfilled Turing&apos;s universal computer.
            We&apos;re building von Neumann&apos;s universal constructor.&rdquo;
          </p>
          <p className="mt-10 font-bold text-text-primary">Nextis</p>
          <p className="mt-1 text-[13px] text-text-tertiary">Hamburg, Germany</p>
          <div className="mt-6 flex justify-center gap-6">
            {[
              { href: "/about", label: "About" },
              { href: "https://github.com/FLASH-73/AURA", label: "GitHub", ext: true },
              { href: "mailto:roberto@nextis.tech", label: "Contact" },
            ].map((l) => (
              <a key={l.label} href={l.href} {...(l.ext ? { target: "_blank", rel: "noopener noreferrer" } : {})} className="text-[12px] text-text-tertiary underline underline-offset-2 transition-colors hover:text-text-primary">
                {l.label}
              </a>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
