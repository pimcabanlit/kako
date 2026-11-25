import { Suspense } from "react";

import { MoneySkeleton, MoneyView } from "@/components/money-view";

// The view is in the address (?view=), read on the client: the screen waits for it.
export default function MoneyPage() {
  return (
    <Suspense fallback={<MoneySkeleton />}>
      <MoneyView />
    </Suspense>
  );
}
