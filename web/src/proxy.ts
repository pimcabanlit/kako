import { type NextRequest, NextResponse } from "next/server";

import { isLoopbackHost, isPublicPicture } from "@/lib/hosts";

/** Until there is sign-in, the web app answers only to a request addressed to this computer
 * (src/lib/hosts.ts says why). Every request, pages and /api/v1 alike, before any rewrite; only the
 * pictures in public/, by their exact paths, are let through on any Host, as the image optimizer
 * asks for them with none. */
export function proxy(request: NextRequest) {
  if (isLoopbackHost(request.headers.get("host")) || isPublicPicture(request.nextUrl.pathname)) {
    return NextResponse.next();
  }
  return new NextResponse("Kako answers only on this computer: open http://localhost:3000.", {
    status: 400,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}
