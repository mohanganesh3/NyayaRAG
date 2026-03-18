export type FrontendAuthProvider = "clerk" | "dev_header" | "anonymous";

export type FrontendAuthSession = {
  displayName: string | null;
  isAuthenticated: boolean;
  provider: FrontendAuthProvider;
  userId: string | null;
};

export function resolveFrontendAuthSession(): FrontendAuthSession {
  const devUserId =
    process.env.NEXT_PUBLIC_DEV_AUTH_USER_ID ??
    (process.env.NODE_ENV === "production" ? null : "dev-advocate");

  if (devUserId) {
    return {
      isAuthenticated: true,
      provider: "dev_header",
      userId: devUserId,
      displayName: "Local Advocate Session",
    };
  }

  if (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return {
      isAuthenticated: false,
      provider: "clerk",
      userId: null,
      displayName: null,
    };
  }

  return {
    isAuthenticated: false,
    provider: "anonymous",
    userId: null,
    displayName: null,
  };
}

export function buildFrontendAuthHeaders(
  session: FrontendAuthSession,
): Record<string, string> {
  if (!session.isAuthenticated || !session.userId) {
    return {};
  }

  if (session.provider === "dev_header") {
    return {
      "X-Nyayarag-Dev-User-Id": session.userId,
    };
  }

  return {
    "X-Clerk-User-Id": session.userId,
    ...(session.displayName
      ? { "X-Clerk-Display-Name": session.displayName }
      : {}),
  };
}
