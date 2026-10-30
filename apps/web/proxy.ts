import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Without a session cookie the session check can only answer 401, and on a cold hosted API that answer took ~10 s while
// the app shell drew an empty dashboard. Send such visitors to sign-in before any page renders. This is an optimistic
// check only: a cookie that is present but expired or revoked is still refused by the API (/api/v1/me → 401 → sign-in).
export function proxy(request: NextRequest) {
  if (request.cookies.has("sl_session")) return NextResponse.next();          // the matcher already skips these; belt and braces
  const { pathname, search } = request.nextUrl;
  const login = new URL("/login", request.url);
  if (pathname !== "/") login.searchParams.set("next", pathname + search);
  else if (search) login.searchParams.set("next", "/" + search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: [{
    // app pages only: not sign-in, the API proxy, health, Next.js assets or files with an extension
    source: "/((?!login|api/|health|_next/|.*\\.[A-Za-z0-9]+$).*)",
    missing: [{ type: "cookie", key: "sl_session" }],
  }],
};
