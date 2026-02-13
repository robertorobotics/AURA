import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AURA — Documentation",
  description:
    "AURA platform documentation — API reference, guides, and architecture",
};

export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
