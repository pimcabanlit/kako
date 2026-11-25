import { Suspense } from "react";

import { DecisionsView, ShelfSkeleton } from "@/components/decisions-view";

// The open book is in the address (?book=, ?mark=), read on the client: the shelf waits for it.
export default function DecisionsPage() {
  return (
    <Suspense fallback={<ShelfSkeleton />}>
      <DecisionsView />
    </Suspense>
  );
}
