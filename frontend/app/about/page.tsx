import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About Nextis — AURA",
  description: "The team and vision behind AURA, the universal assembly automation platform.",
};

export default function AboutPage() {
  const body = "mt-4 text-[15px] leading-[1.7] text-text-secondary";
  const sectionTitle = "text-[22px] font-bold text-text-primary mt-16";
  const link = "text-text-tertiary underline underline-offset-3";

  return (
    <div className="h-screen overflow-y-auto">
      <main className="mx-auto max-w-[680px] px-6 pt-20 pb-24">
        <a href="/landing" className="text-[13px] text-text-tertiary">
          ← AURA
        </a>

        {/* Header */}
        <section className="mt-8">
          <h1 className="text-[32px] font-extrabold tracking-tight text-text-primary">
            About Nextis
          </h1>
          <p className={body}>
            Nextis is building universal assembly automation. Why does it take six months to
            program a robot to build something new? AURA is our answer — a platform that turns
            CAD files into autonomous assembly programs in days, not months.
          </p>
        </section>

        {/* What We're Building */}
        <section>
          <h2 className={sectionTitle}>What We&apos;re Building</h2>
          <p className={body}>
            AURA is a complete vertical stack: from Damiao quasi-direct-drive motor control and
            force-feedback teleoperation to per-step learned manipulation policies, all
            orchestrated by a state machine that walks an assembly graph extracted from CAD
            geometry.
          </p>
          <p className={body}>
            The core insight: you don&apos;t need a general-purpose manipulation model to automate
            assembly. You need motion primitives for the easy steps and learned policies for the
            hard ones, trained from a handful of force-feedback demonstrations.
          </p>
          <p className={body}>
            We&apos;re focused on small-to-medium mechanical assemblies — gearboxes, motors,
            consumer electronics. The platform is designed to generalize from day one.
          </p>
        </section>

        {/* The Team */}
        <section>
          <h2 className={sectionTitle}>The Team</h2>
          <div className="mt-6">
            <p className="text-[16px] font-bold text-text-primary">Roberto De la Cruz</p>
            <p className="mt-0.5 text-[14px] text-text-tertiary">Founder</p>
            <p className={body}>
              Physics BSc. Paused Master&apos;s in Robotics at TUM to build Nextis full-time.
              Three years building robotic arms from first principles — CAD design, motor control
              firmware, force feedback, ML training pipelines. Working from a garage workshop in
              Hamburg.
            </p>
            <div className="mt-4 flex gap-4 text-[13px]">
              <a
                href="https://github.com/FLASH-73"
                target="_blank"
                rel="noopener noreferrer"
                className={link}
              >
                GitHub
              </a>
              <a href="mailto:roberto@nextis.tech" className={link}>
                roberto@nextis.tech
              </a>
            </div>
          </div>
        </section>

        {/* The Vision */}
        <section>
          <h2 className={sectionTitle}>The Vision</h2>
          <p className={body}>
            The universal constructor is von Neumann&apos;s idea — a machine that can build
            anything, including parts of itself. The personal computer fulfilled Turing&apos;s
            universal computer. We believe assembly automation will follow the same arc: from
            industrial to personal.
          </p>
          <p className={body}>
            We&apos;re starting with factories. We&apos;re aiming for everywhere.
          </p>
        </section>

        {/* Open Source */}
        <section>
          <h2 className={sectionTitle}>Open Source</h2>
          <p className={body}>
            AURA is open source.{" "}
            <a
              href="https://github.com/FLASH-73/AURA"
              target="_blank"
              rel="noopener noreferrer"
              className={link}
            >
              github.com/FLASH-73/AURA
            </a>
          </p>
          <p className={body}>
            If you&apos;re working on assembly automation, building robots, or interested in what
            we&apos;re doing — reach out.
          </p>
          <p className={body}>
            <a href="mailto:roberto@nextis.tech" className={link}>
              roberto@nextis.tech
            </a>
          </p>
        </section>
      </main>
    </div>
  );
}
