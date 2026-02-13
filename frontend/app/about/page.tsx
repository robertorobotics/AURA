import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About Nextis — AURA",
  description: "The team and vision behind AURA, the universal assembly automation platform.",
};

export default function AboutPage() {
  const navLink = "text-[13px] text-text-secondary hover:text-text-primary";
  const sectionTitle = "text-[24px] font-bold text-text-primary";
  const body = "mt-4 text-[15px] leading-[1.7] text-text-secondary";
  const link =
    "text-accent underline underline-offset-2 transition-colors hover:text-accent-hover";

  return (
    <div className="h-screen overflow-y-auto scroll-smooth">
      <nav className="sticky top-0 z-50 flex items-center justify-between border-b border-bg-tertiary bg-bg-primary/92 px-6 py-3 backdrop-blur-lg">
        <div className="flex items-center gap-2">
          <a href="/landing" className="text-[16px] font-bold tracking-[0.2em] text-text-primary">
            AURA
          </a>
          <span className="text-[13px] text-text-tertiary">by Nextis</span>
        </div>
        <div className="flex items-center gap-6">
          <a href="/landing#product" className={navLink}>Product</a>
          <a href="/landing#technology" className={navLink}>Technology</a>
          <a href="/about" className={`${navLink} text-text-primary`}>About</a>
          <a
            href="/"
            className="rounded-md bg-accent px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover"
          >
            Open Platform
          </a>
        </div>
      </nav>

      <main className="mx-auto max-w-[680px] px-6 pt-20 pb-24">
        <section>
          <h1 className="text-[36px] font-extrabold tracking-tight text-text-primary">
            About Nextis
          </h1>
          <p className={body}>
            Nextis is building universal assembly automation. We started with a question: why does
            it take 6 months to program a robot to build something new? AURA is our answer — a
            platform that turns CAD files into autonomous assembly programs in days, not months.
          </p>
        </section>

        <section className="mt-16">
          <h2 className={sectionTitle}>What We&apos;re Building</h2>
          <p className={body}>
            AURA is a complete vertical stack: from motor control and force-feedback teleoperation
            to per-step learned manipulation policies.
          </p>
          <p className={body}>
            The core insight: you don&apos;t need a general-purpose manipulation model to automate
            assembly. You need primitives for the easy steps and learned policies for the hard ones,
            trained from a handful of demonstrations.
          </p>
          <p className={body}>
            We&apos;re currently focused on small-to-medium mechanical assemblies — gearboxes,
            motors, consumer electronics. The platform is designed to generalize.
          </p>
        </section>

        <section className="mt-16">
          <h2 className={sectionTitle}>The Team</h2>
          <div className="mt-6">
            <p className="text-[15px] font-semibold text-text-primary">Roberto De la Cruz</p>
            <p className="mt-0.5 text-[13px] text-text-tertiary">Founder</p>
            <ul className="mt-3 list-inside list-disc space-y-1.5 text-[15px] leading-[1.7] text-text-secondary">
              <li>Physics BSc. Paused Master&apos;s in Robotics at TUM to build Nextis full-time.</li>
              <li>
                Three years building robotic arms. From first principles — CAD, motor control, force
                feedback, ML training pipelines.
              </li>
              <li>Based in Hamburg, Germany. Building from a garage workshop.</li>
            </ul>
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

        <section className="mt-16">
          <h2 className={sectionTitle}>The Vision</h2>
          <p className={body}>
            The universal constructor is von Neumann&apos;s idea — a machine that can build
            anything, including copies of itself. The PC fulfilled Turing&apos;s universal computer.
            We believe assembly automation will follow the same trajectory: from industrial to
            personal.
          </p>
          <p className={body}>
            We&apos;re starting with factories. We&apos;re aiming for everywhere.
          </p>
        </section>

        <section className="mt-16">
          <h2 className={sectionTitle}>Open Source + Contact</h2>
          <p className={body}>
            AURA is open source:{" "}
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
