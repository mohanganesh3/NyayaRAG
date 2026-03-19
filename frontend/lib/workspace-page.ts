import type { FrontendAuthSession } from "./auth-session";
import { demoQueryHistoryForSession } from "./query-history";
import {
  demoWorkspaceContext,
  demoWorkspaceListItem,
  type SavedWorkspaceAnswerRecord,
  type WorkspaceCaseContext,
  type WorkspaceListItem,
} from "./workspace";
import {
  fetchWorkspace,
  fetchWorkspaceHistory,
  fetchWorkspaceList,
  fetchWorkspaceSavedAnswers,
} from "./workspace-api";

export type WorkspacePageData = {
  availableWorkspaces: WorkspaceListItem[];
  context: WorkspaceCaseContext;
  queryHistory: ReturnType<typeof demoQueryHistoryForSession>;
  savedAnswers: SavedWorkspaceAnswerRecord[];
  source: "fallback" | "live";
};

function normalizeRequestedCaseId(
  value: string | string[] | undefined,
): string | null {
  if (typeof value === "string" && value.length > 0) {
    return value;
  }
  if (Array.isArray(value) && typeof value[0] === "string" && value[0].length > 0) {
    return value[0];
  }
  return null;
}

export async function getWorkspacePageData(args: {
  authHeaders: Record<string, string>;
  authSession: FrontendAuthSession;
  requestedCaseId?: string | string[];
}): Promise<WorkspacePageData> {
  const requestedCaseId = normalizeRequestedCaseId(args.requestedCaseId);
  const fallbackData: WorkspacePageData = {
    availableWorkspaces: [demoWorkspaceListItem],
    context: demoWorkspaceContext,
    queryHistory: demoQueryHistoryForSession(
      args.authSession,
      demoWorkspaceContext.case_id,
    ),
    savedAnswers: [],
    source: "fallback",
  };

  if (process.env.NODE_ENV === "test" || !args.authSession.isAuthenticated) {
    return fallbackData;
  }

  const availableWorkspaces = await fetchWorkspaceList({
    authHeaders: args.authHeaders,
  });

  if (availableWorkspaces.length === 0) {
    return fallbackData;
  }

  const selectedWorkspace =
    availableWorkspaces.find((workspace) => workspace.case_id === requestedCaseId) ??
    availableWorkspaces[0];

  const [context, queryHistory, savedAnswers] = await Promise.all([
    fetchWorkspace({
      authHeaders: args.authHeaders,
      caseId: selectedWorkspace.case_id,
    }),
    fetchWorkspaceHistory({
      authHeaders: args.authHeaders,
      caseId: selectedWorkspace.case_id,
    }),
    fetchWorkspaceSavedAnswers({
      authHeaders: args.authHeaders,
      caseId: selectedWorkspace.case_id,
    }),
  ]);

  return {
    availableWorkspaces,
    context,
    queryHistory,
    savedAnswers,
    source: "live",
  };
}
