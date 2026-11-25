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

// The pictures in public/, by their exact paths (hosts.test.ts holds this list to the folder).
// Next.js's image optimizer reads each with a request of its own that carries no Host at all, so
// the Host check would refuse them and every picture would show broken. They are the same files
// the public repo holds, so serving them on any Host gives nothing away. A list, not a pattern:
// a page, a route or an /api path that merely ends in ".png" keeps the Host check.
export const PUBLIC_PICTURES: ReadonlySet<string> = new Set(["/kako-mark.png", "/swirl.jpg"]);

/** Whether a request's path is one of the pictures in public/, which need no Host check. */
export function isPublicPicture(pathname: string): boolean {
  return PUBLIC_PICTURES.has(pathname);
}
