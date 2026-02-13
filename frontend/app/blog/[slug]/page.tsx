import Link from "next/link";
import { notFound } from "next/navigation";
import { blogPosts, getPostBySlug } from "@/lib/blog-posts";

const navLink = "text-[13px] text-text-secondary hover:text-text-primary";

export function generateStaticParams() {
  return blogPosts.map((post) => ({ slug: post.slug }));
}

export default async function BlogPostPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = getPostBySlug(slug);

  if (!post) {
    notFound();
  }

  const paragraphs = post.content.split("\n\n");

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

      <main className="mx-auto max-w-[680px] px-6 py-16">
        <Link
          href="/blog"
          className="text-[13px] text-text-tertiary transition-colors hover:text-text-primary"
        >
          &larr; All Updates
        </Link>

        <time className="mt-6 block font-mono text-[13px] text-text-tertiary">
          {new Date(post.date).toLocaleDateString("en-US", {
            year: "numeric",
            month: "long",
            day: "numeric",
          })}
        </time>

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

        <h1 className="mt-2 text-[32px] font-bold leading-tight text-text-primary">
          {post.title}
        </h1>

        <div className="mt-8">
          {paragraphs.map((p, i) => (
            <p
              key={i}
              className="mt-5 first:mt-0 text-[15px] leading-[1.75] text-text-secondary"
            >
              {p}
            </p>
          ))}
        </div>
      </main>
    </div>
  );
}
