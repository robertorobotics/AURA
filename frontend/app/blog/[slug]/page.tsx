import Link from "next/link";
import { notFound } from "next/navigation";
import { BLOG_POSTS, getPostBySlug } from "@/lib/blog-posts";

export function generateStaticParams() {
  return BLOG_POSTS.map((post) => ({ slug: post.slug }));
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
    <main className="mx-auto max-w-[680px] px-6 pt-20">
      <Link
        href="/blog"
        className="text-[13px] text-text-tertiary transition-colors hover:text-text-primary"
      >
        &larr; All Updates
      </Link>

      <time className="mt-6 block font-mono text-[12px] text-text-tertiary">
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

      <h1 className="mt-3 text-[32px] font-[800] leading-tight text-text-primary">
        {post.title}
      </h1>

      <div className="mt-8">
        {paragraphs.map((p, i) => (
          <p
            key={i}
            className="mb-5 text-[15px] leading-[1.75] text-text-secondary"
          >
            {p}
          </p>
        ))}
      </div>
    </main>
  );
}
