import type { FrontendAuthSession } from "./auth-session";

export type WorkspaceQueryHistoryPreview = {
  createdAt: string;
  pipeline: string;
  query: string;
  status: "completed" | "running" | "error";
  workspaceId: string;
};

export function demoQueryHistoryForSession(
  session: FrontendAuthSession,
  workspaceId: string,
): WorkspaceQueryHistoryPreview[] {
  if (!session.isAuthenticated) {
    return [];
  }

  return [
    {
      query: "What are the strongest anticipatory bail arguments on these facts?",
      pipeline: "agentic_rag",
      status: "completed",
      createdAt: "2026-03-19 09:14",
      workspaceId,
    },
    {
      query: "Which Supreme Court authority should lead the note?",
      pipeline: "hybrid_crag",
      status: "completed",
      createdAt: "2026-03-18 19:42",
      workspaceId,
    },
    {
      query: "What prosecution weaknesses should be answered in reply?",
      pipeline: "graph_hybrid",
      status: "running",
      createdAt: "2026-03-18 17:05",
      workspaceId,
    },
  ];
}
