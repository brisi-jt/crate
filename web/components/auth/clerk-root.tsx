"use client";

import { ClerkProvider, useAuth } from "@clerk/nextjs";
import { useEffect } from "react";
import { setAuthTokenProvider } from "@/lib/api/client";

/**
 * Feeds Clerk session tokens into the API client so every request carries a
 * bearer JWT. The API's get_current_user dependency verifies it and maps the
 * Clerk user id onto a crate user row.
 */
function TokenBridge() {
  const { getToken } = useAuth();
  useEffect(() => {
    setAuthTokenProvider(() => getToken());
    return () => setAuthTokenProvider(null);
  }, [getToken]);
  return null;
}

export function ClerkAuthRoot({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <TokenBridge />
      {children}
    </ClerkProvider>
  );
}
