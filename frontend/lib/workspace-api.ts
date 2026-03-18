import type { WorkspaceQueryHistoryPreview } from "./query-history";
import {
  normalizeWorkspaceContext,
  type WorkspaceCaseContext,
} from "./workspace";

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type WorkspaceApiRecord = Record<string, unknown>;

function asRecord(value: unknown): WorkspaceApiRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as WorkspaceApiRecord)
    : null;
}

function readErrorMessage(value: unknown): string {
  const record = asRecord(value);
  const errorRecord = asRecord(record?.error);
  const message = errorRecord?.message;
  return typeof message === "string" && message.length > 0
    ? message
    : "The workspace request failed.";
}

function normalizeHistoryEntry(value: unknown): WorkspaceQueryHistoryPreview | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const status = record.status;
  const createdAt = record.created_at;
  const query = record.query;
  const pipeline = record.pipeline;
  const workspaceId = record.workspace_id;

  if (
    typeof query !== "string" ||
    typeof pipeline !== "string" ||
    typeof workspaceId !== "string"
  ) {
    return null;
  }

  return {
    createdAt: typeof createdAt === "string" ? createdAt : "",
    pipeline,
    query,
    status:
      status === "completed" || status === "running" || status === "error"
        ? status
        : "error",
    workspaceId,
  };
}

export async function uploadWorkspaceDocuments(args: {
  authHeaders: Record<string, string>;
  caseId?: string;
  caseNumber?: string | null;
  court?: string | null;
  files: File[];
}): Promise<WorkspaceCaseContext> {
  const formData = new FormData();
  for (const file of args.files) {
    formData.append("files", file);
  }
  if (args.caseId) {
    formData.append("case_id", args.caseId);
  }
  if (args.court) {
    formData.append("court", args.court);
  }
  if (args.caseNumber) {
    formData.append("case_number", args.caseNumber);
  }

  const response = await fetch(`${apiBaseUrl}/api/workspace/upload`, {
    method: "POST",
    headers: {
      ...args.authHeaders,
    },
    body: formData,
  });
  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    throw new Error(readErrorMessage(payload));
  }

  const record = asRecord(payload);
  const normalized = normalizeWorkspaceContext(record?.data);
  if (!normalized) {
    throw new Error("Workspace upload completed, but the response payload was invalid.");
  }

  return normalized;
}

export async function fetchWorkspaceHistory(args: {
  authHeaders: Record<string, string>;
  caseId: string;
}): Promise<WorkspaceQueryHistoryPreview[]> {
  const response = await fetch(`${apiBaseUrl}/api/workspace/${args.caseId}/history`, {
    headers: {
      ...args.authHeaders,
    },
  });
  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    throw new Error(readErrorMessage(payload));
  }

  const record = asRecord(payload);
  const items = Array.isArray(record?.data) ? record.data : [];
  return items
    .map(normalizeHistoryEntry)
    .filter((entry): entry is WorkspaceQueryHistoryPreview => entry !== null);
}
