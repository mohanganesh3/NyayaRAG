import type { WorkspaceQueryHistoryPreview } from "./query-history";
import {
  normalizeWorkspaceContext,
  type WorkspaceCaseContext,
} from "./workspace";

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type WorkspaceApiRecord = Record<string, unknown>;

export type WorkspaceCitationSource = {
  actName: string | null;
  appealStatus: string;
  appealWarning: string | null;
  citation: string | null;
  currentValidity: string;
  date: string | null;
  docId: string;
  docType: string;
  effectiveCitation: string | null;
  effectiveDocId: string;
  pathDocIds: string[];
  sectionHeader: string | null;
  sectionNumber: string | null;
  sourceDocumentRef: string | null;
  sourcePassage: string | null;
  sourceSystem: string | null;
  sourceUrl: string | null;
  title: string;
};

function asRecord(value: unknown): WorkspaceApiRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as WorkspaceApiRecord)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
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

function normalizeCitationSource(value: unknown): WorkspaceCitationSource | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const docId = readString(record.doc_id);
  const effectiveDocId = readString(record.effective_doc_id);
  const title = readString(record.title);
  const appealStatus = readString(record.appeal_status);
  const currentValidity = readString(record.current_validity);
  const docType = readString(record.doc_type);

  if (!docId || !effectiveDocId || !title || !appealStatus || !currentValidity || !docType) {
    return null;
  }

  return {
    actName: readString(record.act_name),
    appealStatus,
    appealWarning: readString(record.appeal_warning),
    citation: readString(record.citation),
    currentValidity,
    date: readString(record.date),
    docId,
    docType,
    effectiveCitation: readString(record.effective_citation),
    effectiveDocId,
    pathDocIds: Array.isArray(record.path_doc_ids)
      ? record.path_doc_ids.filter((item): item is string => typeof item === "string")
      : [],
    sectionHeader: readString(record.section_header),
    sectionNumber: readString(record.section_number),
    sourceDocumentRef: readString(record.source_document_ref),
    sourcePassage: readString(record.source_passage),
    sourceSystem: readString(record.source_system),
    sourceUrl: readString(record.source_url),
    title,
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

export async function fetchCitationSource(args: {
  authHeaders?: Record<string, string>;
  chunkId?: string | null;
  docId: string;
}): Promise<WorkspaceCitationSource> {
  const params = new URLSearchParams();
  if (args.chunkId) {
    params.set("chunk_id", args.chunkId);
  }

  const response = await fetch(
    `${apiBaseUrl}/api/citation/${args.docId}/source${
      params.toString().length > 0 ? `?${params.toString()}` : ""
    }`,
    {
      headers: {
        ...(args.authHeaders ?? {}),
      },
    },
  );
  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    throw new Error(readErrorMessage(payload));
  }

  const record = asRecord(payload);
  const normalized = normalizeCitationSource(record?.data);
  if (!normalized) {
    throw new Error("Citation source lookup completed, but the response payload was invalid.");
  }

  return normalized;
}
