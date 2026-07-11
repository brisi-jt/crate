/**
 * Auth provider selection.
 *
 * Two providers share one seam:
 * - "dev": trivially signed in as the local dev user. The API pairs with this
 *   via its CRATE_DEV_USER setting (crate/deps.py get_current_user bypass) —
 *   no token is attached to requests.
 * - "clerk": Clerk session gating (proxy + provider + JWT on API requests).
 *   Activates as soon as the Clerk env keys exist; see lib/auth/clerk.ts.
 *
 * NEXT_PUBLIC_CRATE_AUTH=dev forces the dev provider even when Clerk keys are
 * present (useful for local runs against the dev-user API stub).
 */
export type AuthMode = "dev" | "clerk";

export function resolveAuthMode(): AuthMode {
  if (process.env.NEXT_PUBLIC_CRATE_AUTH === "dev") return "dev";
  if (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) return "clerk";
  return "dev";
}
