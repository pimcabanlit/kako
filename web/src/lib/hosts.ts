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
