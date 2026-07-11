import { clerkMiddleware } from "@clerk/nextjs/server";
import { type NextRequest, NextResponse } from "next/server";
import { resolveAuthMode } from "@/lib/auth/mode";

/**
 * Request gate (Next.js proxy convention — the renamed middleware file).
 *
 * Clerk mode: every route requires a session, and the signed-in user's email
 * must appear in CRATE_ALLOWED_EMAILS (comma-separated). The email arrives via
 * the `email` session-token claim — Clerk dashboard > Sessions > Customize
 * session token > add {"email": "{{user.primary_email_address}}"}.
 *
 * Dev mode: pass-through; the API resolves its own dev user.
 */
const clerkGate = clerkMiddleware(async (auth, req) => {
  const { userId, sessionClaims, redirectToSignIn } = await auth();
  if (!userId) return redirectToSignIn();

  const allowed = (process.env.CRATE_ALLOWED_EMAILS ?? "")
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean);
  if (allowed.length === 0) return;

  const email = (sessionClaims?.email as string | undefined)?.toLowerCase();
  if (!email || !allowed.includes(email)) {
    return NextResponse.rewrite(new URL("/unauthorized", req.url));
  }
});

function devGate(_req: NextRequest) {
  return NextResponse.next();
}

export default resolveAuthMode() === "clerk" ? clerkGate : devGate;

export const config = {
  matcher: [
    // Skip Next internals and static assets.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
