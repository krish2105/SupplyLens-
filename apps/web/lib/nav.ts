/** Where to go after sign-in (P3-FE-09): the `next` path the session ended on, only ever a path on this site. A full URL,
 *  a protocol-relative `//host`, a backslash trick or the sign-in page itself fall back to the overview. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\") || next.startsWith("/login")) return "/";
  return next;
}
