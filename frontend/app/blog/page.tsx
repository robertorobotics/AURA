import Link from "next/link";
import { BLOG_POSTS } from "@/lib/blog-posts";

export default function BlogIndexPage() {
  const sorted = [...BLOG_POSTS].sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
  );

  return (
    <main className="mx-auto max-w-[800px] px-6 pt-20">
      <Link
        href="/landing"
        className="text-[13px] text-text-tertiary transition-colors hover:text-text-primary"
      >
        &larr; AURA
      </Link>

      <h1 className="mt-6 text-[32px] font-[800] text-text-primary">
        Updates
      </h1>

      <div className="mt-12 flex flex-col">
        {sorted.map((post, i) => (
          <div
            key={post.slug}
            className={`py-6 ${
              i < sorted.length - 1 ? "border-b border-bg-tertiary" : ""
            }`}
          >
            <time className="font-mono text-[12px] text-text-tertiary">
              {new Date(post.date).toLocaleDateString("en-US", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </time>

            <Link
              href={`/blog/${post.slug}`}
              className="mt-1 block text-[18px] font-[600] text-text-primary hover:underline"
            >
              {post.title}
            </Link>

            <p className="mt-1 text-[13px] text-text-secondary">
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
          </div>
        ))}
      </div>
    </main>
  );
}
