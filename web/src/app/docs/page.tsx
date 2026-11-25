import { redirect } from "next/navigation";

import { docHref, FIRST_PAGE } from "@/lib/docs/index";

/** The documentation opens on its first page, "How Kako uses Meko". */
export default function DocsPage() {
  redirect(docHref(FIRST_PAGE));
}
