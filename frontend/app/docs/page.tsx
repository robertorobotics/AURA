"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  DOCS_CONTENT,
  type ContentBlock,
  type DocSection,
  type RichText,
  type TextRun,
} from "@/lib/docs-content";

// ---------------------------------------------------------------------------
// Rich text renderer
// ---------------------------------------------------------------------------

function renderRun(run: TextRun) {
  let node: React.ReactNode = run.text;
  if (run.code) {
    node = (
      <code className="rounded bg-bg-secondary px-1.5 py-0.5 font-mono text-[12px] text-accent">
        {run.text}
      </code>
    );
  }
  if (run.bold) {
    node = <strong className="font-semibold text-text-primary">{node}</strong>;
  }
  if (run.link) {
    node = (
      <a
        href={run.link.href}
        className="text-accent underline underline-offset-2 hover:text-accent-hover"
        {...(run.link.external
          ? { target: "_blank", rel: "noopener noreferrer" }
          : {})}
      >
        {node}
      </a>
    );
  }
  return node;
}

function RichTextRenderer({ content }: { content: RichText }) {
  if (typeof content === "string") return <>{content}</>;
  if (!Array.isArray(content)) return <>{renderRun(content)}</>;
  return (
    <>
      {content.map((part, i) => (
        <Fragment key={i}>
          {typeof part === "string" ? part : renderRun(part)}
        </Fragment>
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Content block renderer
// ---------------------------------------------------------------------------

function BlockRenderer({ block }: { block: ContentBlock }) {
  switch (block.type) {
    case "paragraph":
      return (
        <p className="text-[14px] leading-relaxed text-text-secondary">
          <RichTextRenderer content={block.content} />
        </p>
      );

    case "code":
      return (
        <pre className="overflow-x-auto rounded-lg bg-text-primary p-4 font-mono text-[13px] leading-relaxed text-bg-primary">
          <code>{block.content}</code>
        </pre>
      );

    case "table":
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr>
                {block.headers.map((h) => (
                  <th
                    key={h}
                    className="border-b border-bg-tertiary px-3 py-2 text-left font-semibold text-text-primary"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className={`border-b border-bg-tertiary/50 px-3 py-2 text-text-secondary ${
                        j === 1 ? "font-mono" : ""
                      }`}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag
          className={`space-y-1 pl-5 text-[14px] text-text-secondary ${
            block.ordered ? "list-decimal" : "list-disc"
          }`}
        >
          {block.items.map((item, i) => (
            <li key={i} className="leading-relaxed">
              <RichTextRenderer content={item} />
            </li>
          ))}
        </Tag>
      );
    }

    case "heading": {
      const Tag = block.level === 3 ? "h3" : "h4";
      const cls =
        block.level === 3
          ? "text-[16px] font-semibold text-text-primary mt-8 mb-3"
          : "text-[14px] font-semibold text-text-primary mt-6 mb-2";
      return <Tag className={cls}>{block.text}</Tag>;
    }

    case "callout":
      return (
        <div
          className={`rounded-lg border-l-[3px] p-4 text-[13px] leading-relaxed ${
            block.variant === "warning"
              ? "border-l-status-warning bg-status-warning-bg text-text-secondary"
              : "border-l-signal bg-signal-light text-text-secondary"
          }`}
        >
          <RichTextRenderer content={block.content} />
        </div>
      );
  }
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function Sidebar({
  sections,
  activeId,
  onNavigate,
}: {
  sections: DocSection[];
  activeId: string;
  onNavigate: (id: string) => void;
}) {
  return (
    <aside className="sticky top-0 flex h-screen w-[240px] shrink-0 flex-col overflow-y-auto border-r border-bg-tertiary bg-bg-primary pb-8 pt-5">
      <a href="/" className="mb-6 block px-5">
        <span className="text-[16px] font-bold tracking-[0.2em] text-text-primary">
          AURA
        </span>
      </a>

      {sections.map((section) => (
        <div key={section.id} className="mb-4">
          <p className="px-5 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">
            {section.title}
          </p>
          <div className="flex flex-col">
            {section.subsections.map((sub) => {
              const isActive = activeId === sub.id;
              return (
                <button
                  key={sub.id}
                  onClick={() => onNavigate(sub.id)}
                  className={`px-5 py-1.5 text-left text-[13px] transition-colors ${
                    isActive
                      ? "border-l-[2px] border-l-accent bg-accent-light font-semibold text-text-primary"
                      : "border-l-[2px] border-l-transparent text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {sub.title}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Docs page
// ---------------------------------------------------------------------------

export default function DocsPage() {
  const [activeId, setActiveId] = useState(
    DOCS_CONTENT[0]?.subsections[0]?.id ?? "",
  );
  const contentRef = useRef<HTMLDivElement>(null);

  // --- IntersectionObserver: track which subsection heading is visible ---
  useEffect(() => {
    const container = contentRef.current;
    if (!container) return;

    const headings = container.querySelectorAll<HTMLElement>("h2[id]");
    if (!headings.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) {
          setActiveId(visible[0].target.id);
        }
      },
      {
        root: container,
        rootMargin: "-80px 0px -60% 0px",
        threshold: 0,
      },
    );

    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, []);

  // --- Scroll to section ---
  const handleNavigate = useCallback((id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
      setActiveId(id);
    }
  }, []);

  return (
    <div className="flex h-screen bg-bg-primary">
      {/* Sidebar */}
      <Sidebar
        sections={DOCS_CONTENT}
        activeId={activeId}
        onNavigate={handleNavigate}
      />

      {/* Content */}
      <div ref={contentRef} className="flex-1 overflow-y-auto">
        {/* Top nav */}
        <nav className="sticky top-0 z-10 flex items-center justify-between border-b border-bg-tertiary bg-bg-primary/92 px-8 py-3 backdrop-blur-lg">
          <div className="flex items-center gap-3">
            <span className="text-[14px] font-semibold text-text-primary">
              Documentation
            </span>
          </div>
          <a
            href="/"
            className="rounded-md bg-accent px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover"
          >
            Open Platform &rarr;
          </a>
        </nav>

        {/* Sections */}
        <div className="mx-auto max-w-[720px] px-8 py-12">
          {DOCS_CONTENT.map((section) => (
            <div key={section.id} className="mb-16">
              {section.subsections.map((sub, subIdx) => (
                <div
                  key={sub.id}
                  className={subIdx > 0 ? "mt-12" : ""}
                >
                  <h2
                    id={sub.id}
                    className="scroll-mt-20 text-[20px] font-semibold text-text-primary"
                  >
                    {sub.title}
                  </h2>
                  <div className="mt-4 space-y-4">
                    {sub.blocks.map((block, blockIdx) => (
                      <BlockRenderer key={blockIdx} block={block} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ))}

          {/* Footer */}
          <div className="border-t border-bg-tertiary pt-8 text-center">
            <p className="text-[12px] text-text-tertiary">
              AURA — Autonomous Universal Robotic Assembly
            </p>
            <p className="mt-1 text-[12px] text-text-tertiary">
              <a
                href="https://github.com/FLASH-73/AURA"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-text-secondary"
              >
                GitHub
              </a>
              {" · "}
              <a
                href="mailto:roberto@nextis.tech"
                className="underline underline-offset-2 hover:text-text-secondary"
              >
                Contact
              </a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
