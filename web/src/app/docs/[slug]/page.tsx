import { notFound } from "next/navigation";
import { Suspense } from "react";

import { DocsView } from "@/components/docs-view";
import { docPage, PAGES } from "@/lib/docs/index";

export function generateStaticParams() {
  return PAGES.map((p) => ({ slug: p.slug }));
}

async function DocPageFor({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const page = docPage(slug);
  if (!page) notFound();
  return <DocsView page={page} />;
}

export default function DocsSlugPage({ params }: PageProps<"/docs/[slug]">) {
  return (
    <Suspense>
      <DocPageFor params={params} />
    </Suspense>
  );
}
