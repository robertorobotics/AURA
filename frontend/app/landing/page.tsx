"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useAssembly } from "@/context/AssemblyContext";
import { ArchitectureGrid } from "@/components/landing/ArchitectureGrid";

const LandingViewer = dynamic(
  () =>
    import("@/components/landing/LandingViewer").then((m) => ({
      default: m.LandingViewer,
    })),
  { ssr: false },
);

const STATS = [
  { value: "57", unit: "steps", desc: "Gearbox assembly, fully autonomous" },
  { value: "1\u20132", unit: "days", desc: "Setup time per new product" },
  { value: "< 5", unit: "min", desc: "Per teaching demonstration" },
  { value: "93%", unit: "", desc: "First-run success rate on trained steps" },
];

const PIPELINE = [
  {
    title: "Parse",
    body: "Upload a STEP file and the system extracts every part, detects contact surfaces, generates assembly meshes, and builds a full parts graph. No manual CAD annotation. The parser handles multi-level assemblies with hundreds of components.",
  },
  {
    title: "Plan",
    body: "The planner reads the parts graph and generates a feasible assembly sequence automatically. Simple operations like pick-and-place get assigned motion primitives. Complex operations \u2014 press fits, insertions, screwing \u2014 get flagged for human teaching.",
  },
  {
    title: "Teach",
    body: "An operator demonstrates difficult steps using a force-feedback leader arm. The leader mirrors the follower with gravity compensation and haptic reflection, so the demonstration feels natural. Ten demos of five minutes each is typically enough.",
  },
  {
    title: "Run",
    body: "The execution engine walks the assembly graph step by step. Each step dispatches to either a motion primitive or a learned policy trained from the demonstrations. If a step fails, the system retries and escalates to a human operator as a last resort.",
  },
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

  const navLink = "text-[13px] text-text-secondary hover:text-text-primary";

  return (
    <div className="h-screen overflow-y-auto scroll-smooth">
      <nav className="sticky top-0 z-50 flex items-center justify-between border-b border-bg-tertiary bg-bg-primary/92 px-6 py-3 backdrop-blur-lg">
        <div className="flex items-center gap-2">
          <span className="text-[16px] font-bold tracking-[0.2em] text-text-primary">AURA</span>
          <span className="text-[13px] text-text-tertiary">by Nextis</span>
        </div>
        <div className="flex items-center gap-6">
          <a href="#product" className={navLink}>Product</a>
          <a href="#technology" className={navLink}>Technology</a>
          <a href="/about" className={navLink}>About</a>
          <a href="/blog" className={navLink}>Updates</a>
          <a href="/docs" className={navLink}>Docs</a>
          <a href="/" className="rounded-md bg-accent px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover">Open Platform</a>
        </div>
      </nav>

      <section className="flex min-h-[85vh] items-center px-6 py-16">
        <div className="mx-auto grid max-w-6xl items-center gap-12 md:grid-cols-2">
          <div>
            <span className="inline-block rounded-full bg-accent-light px-3 py-1 text-[12px] font-medium text-accent">
              Assembly Automation Platform
            </span>
            <h1 className="mt-4 whitespace-pre-line text-[48px] font-extrabold leading-[1.1] tracking-tight text-text-primary">
              {"Upload CAD.\nRobot assembles it."}
            </h1>
            <p className="mt-4 max-w-md text-[16px] leading-relaxed text-text-secondary">
              AURA turns STEP files into autonomous assembly programs. Parse the geometry,
              plan the sequence, teach the hard steps, run it.
            </p>
            <div className="mt-8 flex items-center gap-4">
              <a href="/" className="rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover">
                Try Live Demo
              </a>
              <a href="#product" className="rounded-md border border-bg-tertiary px-4 py-2 text-[13px] font-medium text-text-primary transition-colors hover:bg-bg-secondary">
                How It Works &rarr;
              </a>
            </div>
            <p className="mt-3 text-[12px] text-text-tertiary">
              No signup required. Runs in your browser with mock hardware.
            </p>
          </div>
          <div className="aspect-[4/3] w-full overflow-hidden rounded-lg bg-bg-viewer">
            {assembly && <LandingViewer assembly={assembly} />}
          </div>
        </div>
      </section>

      <section className="border-y border-bg-tertiary px-6 py-12">
        <div className="reveal mx-auto grid max-w-5xl grid-cols-2 gap-8 md:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.value} className="text-center">
              <p className="font-mono text-[48px] font-semibold leading-none tabular-nums text-text-primary">
                {s.value}<span className="ml-1 text-[20px] text-text-tertiary">{s.unit}</span>
              </p>
              <p className="mt-2 text-[13px] text-text-secondary">{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="product" className="px-6 py-16 md:py-24">
        <div className="mx-auto max-w-5xl">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">
            How it works
          </p>
          <div className="mt-10 flex gap-8">
            <div className="flex w-[280px] shrink-0 flex-col gap-1">
              {PIPELINE.map((step, i) => (
                <button
                  key={step.title}
                  onClick={() => setActiveTab(i)}
                  className={`flex items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors ${
                    i === activeTab
                      ? "border-l-[3px] border-l-accent bg-accent-light"
                      : "border-l-[3px] border-l-transparent hover:bg-bg-secondary"
                  }`}
                >
                  <span className={`font-mono text-[14px] font-semibold ${i === activeTab ? "text-accent" : "text-text-tertiary"}`}>
                    {i + 1}
                  </span>
                  <span className={`text-[14px] font-medium ${i === activeTab ? "text-text-primary" : "text-text-secondary"}`}>
                    {step.title}
                  </span>
                </button>
              ))}
            </div>
            <div className="flex-1 rounded-lg bg-bg-secondary p-6">
              <h3 className="text-[18px] font-semibold text-text-primary">
                {PIPELINE[activeTab]?.title}
              </h3>
              <p className="mt-3 text-[14px] leading-relaxed text-text-secondary">
                {PIPELINE[activeTab]?.body}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section id="technology" className="px-6 py-16 md:py-24">
        <div className="reveal mx-auto max-w-5xl">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">
            Technology
          </p>
          <p className="mt-3 text-[20px] font-semibold text-text-primary">
            Built for real hardware, not simulation
          </p>
          <div className="mt-10">
            <ArchitectureGrid />
          </div>
        </div>
      </section>

      <section id="about" className="px-6 py-16 md:py-24">
        <div className="reveal mx-auto max-w-3xl text-center">
          <p className="text-[24px] font-light italic leading-[1.8] text-text-secondary">
            &ldquo;The PC fulfilled Turing&apos;s universal computer.
            AURA fulfills von Neumann&apos;s universal constructor.&rdquo;
          </p>
          <p className="mt-10 text-[18px] font-semibold text-text-primary">Nextis</p>
          <p className="mt-1 text-[13px] text-text-tertiary">Hamburg, Germany</p>
          <div className="mt-6 flex justify-center gap-6 text-[13px]">
            {[
              { href: "/about", label: "About" },
              { href: "https://github.com/FLASH-73/AURA", label: "GitHub", ext: true },
              { href: "mailto:roberto@nextis.tech", label: "Contact" },
            ].map((l) => (
              <a key={l.label} href={l.href} {...(l.ext ? { target: "_blank", rel: "noopener noreferrer" } : {})} className="text-text-secondary underline underline-offset-2 transition-colors hover:text-text-primary">
                {l.label}
              </a>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
