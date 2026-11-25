import { Suspense } from "react";

import { SessionView, Skeleton } from "@/components/session-view";

export default function SessionPage({ params }: PageProps<"/sessions/[id]">) {
  return (
    <Suspense fallback={<Skeleton />}>
      {params.then(({ id }) => (
        <SessionView key={id} id={id} />
      ))}
    </Suspense>
  );
}
