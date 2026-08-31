import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Ported from gustavo-ui/middleware.ts. Runtime AUTH_ENABLED (Edge Runtime
// compatible) - not NEXT_PUBLIC_AUTH_ENABLED, which is baked at build time.
const AUTH_ENABLED = process.env.AUTH_ENABLED === "true";
const PUBLIC_PATHS = ["/login", "/api/auth"];

export function middleware(request: NextRequest) {
  if (!AUTH_ENABLED) return NextResponse.next();

  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const token = request.cookies.get("composer_token")?.value;
  if (!token) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/|.*\\.\\w{1,4}$).*)"],
};
