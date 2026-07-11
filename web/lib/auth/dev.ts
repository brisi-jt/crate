/**
 * Dev auth provider: always signed in as the local dev user.
 *
 * The API resolves the acting user from its CRATE_DEV_USER setting, so the
 * web side attaches no credentials — it only needs a display identity.
 */
export interface DevIdentity {
  isSignedIn: true;
  userLabel: string;
}

export function devIdentity(): DevIdentity {
  return {
    isSignedIn: true,
    userLabel: process.env.NEXT_PUBLIC_CRATE_DEV_USER ?? "jt-dev",
  };
}
