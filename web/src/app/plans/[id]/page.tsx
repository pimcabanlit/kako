import { Suspense } from "react";

import { PlanSkeleton, PlanView } from "@/components/plan-view";

export default function PlanPage({ params }: PageProps<"/plans/[id]">) {
  return (
    <Suspense fallback={<PlanSkeleton />}>
      {params.then(({ id }) => (
        <PlanView key={id} id={id} />
      ))}
    </Suspense>
  );
}
