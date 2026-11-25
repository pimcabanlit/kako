// The only Host names the web app answers to, as the backend does (backend/src/kako/api/app.py),
// until there is sign-in. The web app passes /api/v1 to the backend with the backend's own Host,
// so without this check a page on another site, rebinding its name to 127.0.0.1, could reach the
// backend through the web app (DNS rebinding).

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** The Host header's name, lower case, without its port. */
export function hostName(host: string): string {
  const value = host.trim().toLowerCase();
  if (value.startsWith("[")) {
    const end = value.indexOf("]");
    return end === -1 ? value : value.slice(0, end + 1);
  }
  const colon = value.indexOf(":");
  return colon === -1 ? value : value.slice(0, colon);
}

/** Whether a request's Host header names this computer's loopback. A missing Host is refused. */
export function isLoopbackHost(host: string | null): boolean {
  return host !== null && LOOPBACK.has(hostName(host));
}

// A picture in public/ (the swirl art, the logo), by its plain path: never under /api, never with
// "..", "%" or a query. Next.js's image optimizer reads these with a request of its own that carries
// no Host at all, so the Host check would refuse them and every picture would show broken. They are
// the same files the public repo holds, so serving them on any Host gives nothing away; pages and
// /api/v1 keep the Host check.
const PUBLIC_PICTURE = /^\/(?!api(?:\/|$))(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.(?:png|jpe?g|webp|avif|gif|svg|ico)$/;

/** Whether a request's path names a picture in public/, which needs no Host check. */
export function isPublicPicture(pathname: string): boolean {
  return PUBLIC_PICTURE.test(pathname);
}
