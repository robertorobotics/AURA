import Link from "next/link";
import { blogPosts } from "@/lib/blog-posts";

const navLink = "text-[13px] text-text-secondary hover:text-text-primary";

export default function BlogIndexPage() {
  const sorted = [...blogPosts].sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
  );

  return (
    <div className="h-screen overflow-y-auto scroll-smooth">
      <nav className="sticky top-0 z-50 flex items-center justify-between border-b border-bg-tertiary bg-bg-primary/92 px-6 py-3 backdrop-blur-lg">
        <Link href="/landing" className="flex items-center gap-2">
          <span className="text-[16px] font-bold tracking-[0.2em] text-text-primary">
            AURA
          </span>
          <span className="text-[13px] text-text-tertiary">by Nextis</span>
        </Link>
        <div className="flex items-center gap-6">
          <a href="/landing#product" className={navLink}>
            Product
          </a>
          <a href="/landing#technology" className={navLink}>
            Technology
          </a>
          <a href="/landing#about" className={navLink}>
            About
          </a>
          <Link
            href="/blog"
            className="text-[13px] font-medium text-text-primary"
          >
            Updates
          </Link>
          <a
            href="/"
            className="rounded-md bg-accent px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover"
          >
            Open Platform
          </a>
        </div>
      </nav>

      <main className="mx-auto max-w-[800px] px-6 py-16">
        <h1 className="text-[32px] font-bold text-text-primary">Updates</h1>
        <p className="mt-2 text-[15px] text-text-secondary">
          Technical notes on building universal assembly.
        </p>

        <div className="mt-12 flex flex-col">
          {sorted.map((post, i) => (
            <Link
              key={post.slug}
              href={`/blog/${post.slug}`}
              className={`group block py-6 transition-colors hover:bg-bg-secondary/40 ${
                i < sorted.length - 1
                  ? "border-b border-bg-tertiary"
                  : ""
              }`}
            >
              <time className="font-mono text-[13px] text-text-tertiary">
                {new Date(post.date).toLocaleDateString("en-US", {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </time>
              <h2 className="mt-1 text-[16px] font-semibold text-text-primary group-hover:text-accent">
                {post.title}
              </h2>
              <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">
                {post.summary}
              </p>
              <div className="mt-2 flex gap-1.5">
                {post.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-bg-secondary px-2 py-0.5 text-[11px] text-text-tertiary"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}
