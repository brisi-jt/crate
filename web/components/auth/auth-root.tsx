"use client";

import { resolveAuthMode } from "@/lib/auth/mode";
import { ClerkAuthRoot } from "./clerk-root";

/**
 * Wraps the app in the active auth provider. Dev mode needs no provider at
 * all — the API resolves its own dev user and requests carry no token.
 */
export function AuthRoot({ children }: { children: React.ReactNode }) {
  if (resolveAuthMode() === "clerk") {
    return <ClerkAuthRoot>{children}</ClerkAuthRoot>;
  }
  return <>{children}</>;
}
