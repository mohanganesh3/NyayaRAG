export type WorkspaceCaseType =
  | "criminal"
  | "civil"
  | "constitutional"
  | "family"
  | "corporate"
  | "tax"
  | "labour"
  | "property"
  | "consumer"
  | "arbitration";

export type WorkspaceCaseStage =
  | "investigation"
  | "bail"
  | "charges"
  | "trial"
  | "appeal"
  | "execution"
  | "revision";

export type WorkspaceTimelineItem = {
  date?: string;
  detail: string;
  label: string;
};

export type WorkspaceOrderItem = {
  court: string;
  date?: string;
  outcome: string;
};

export type WorkspaceUploadedDocument = {
  confidence: number;
  document_type: string;
  name: string;
  pages: number;
};

export type WorkspaceCaseContext = {
  advocates: string[];
  appellant_petitioner: string | null;
  bail_history: WorkspaceOrderItem[];
  bnss_equivalents: string[];
  case_id: string;
  case_number: string | null;
  case_type: WorkspaceCaseType | null;
  charges_sections: string[];
  court: string | null;
  doc_extraction_confidence: number;
  key_facts: WorkspaceTimelineItem[];
  open_legal_issues: string[];
  previous_orders: WorkspaceOrderItem[];
  respondent_opposite_party: string | null;
  stage: WorkspaceCaseStage | null;
  statutes_involved: string[];
  uploaded_docs: WorkspaceUploadedDocument[];
};

type WorkspaceRecord = Record<string, unknown>;

function asRecord(value: unknown): WorkspaceRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as WorkspaceRecord)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function normalizeTimelineItems(value: unknown): WorkspaceTimelineItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const normalized: WorkspaceTimelineItem[] = [];

  for (const item of value) {
    const record = asRecord(item);
    if (!record) {
      continue;
    }

    normalized.push({
      date: readString(record.date) ?? undefined,
      detail: readString(record.detail) ?? "",
      label: readString(record.label) ?? "Undifferentiated event",
    });
  }

  return normalized;
}

function normalizeOrders(value: unknown): WorkspaceOrderItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const normalized: WorkspaceOrderItem[] = [];

  for (const item of value) {
    const record = asRecord(item);
    if (!record) {
      continue;
    }

    normalized.push({
      court: readString(record.court) ?? "Unknown court",
      date: readString(record.date) ?? undefined,
      outcome:
        readString(record.outcome) ??
        readString(record.status) ??
        "No outcome extracted",
    });
  }

  return normalized;
}

function normalizeUploadedDocuments(value: unknown): WorkspaceUploadedDocument[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      const record = asRecord(item);
      if (!record) {
        return null;
      }

      return {
        confidence:
          typeof record.confidence === "number" ? record.confidence : 0,
        document_type:
          readString(record.document_type) ??
          readString(record.document_mode) ??
          "uploaded_document",
        name: readString(record.name) ?? "Uploaded document",
        pages:
          typeof record.pages === "number"
            ? record.pages
            : typeof record.page_count === "number"
              ? record.page_count
              : 1,
      };
    })
    .filter((item): item is WorkspaceUploadedDocument => item !== null);
}

export function normalizeWorkspaceContext(
  value: unknown,
): WorkspaceCaseContext | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  return {
    advocates: Array.isArray(record.advocates)
      ? record.advocates.filter((item): item is string => typeof item === "string")
      : [],
    appellant_petitioner: readString(record.appellant_petitioner),
    bail_history: normalizeOrders(record.bail_history),
    bnss_equivalents: Array.isArray(record.bnss_equivalents)
      ? record.bnss_equivalents.filter(
          (item): item is string => typeof item === "string",
        )
      : [],
    case_id: readString(record.case_id) ?? "workspace-unavailable",
    case_number: readString(record.case_number),
    case_type:
      (readString(record.case_type) as WorkspaceCaseType | null) ?? null,
    charges_sections: Array.isArray(record.charges_sections)
      ? record.charges_sections.filter(
          (item): item is string => typeof item === "string",
        )
      : [],
    court: readString(record.court),
    doc_extraction_confidence:
      typeof record.doc_extraction_confidence === "number"
        ? record.doc_extraction_confidence
        : 0,
    key_facts: normalizeTimelineItems(record.key_facts),
    open_legal_issues: Array.isArray(record.open_legal_issues)
      ? record.open_legal_issues.filter(
          (item): item is string => typeof item === "string",
        )
      : [],
    previous_orders: normalizeOrders(record.previous_orders),
    respondent_opposite_party: readString(record.respondent_opposite_party),
    stage: (readString(record.stage) as WorkspaceCaseStage | null) ?? null,
    statutes_involved: Array.isArray(record.statutes_involved)
      ? record.statutes_involved.filter(
          (item): item is string => typeof item === "string",
        )
      : [],
    uploaded_docs: normalizeUploadedDocuments(record.uploaded_docs),
  };
}

export function workspaceContextStorageKey(authUserId: string | null): string {
  return `nyayarag.workspace.active.${authUserId ?? "anonymous"}`;
}

export function workspaceHistoryStorageKey(caseId: string): string {
  return `nyayarag.workspace.history.${caseId}`;
}

export function workspaceSavedAnswersStorageKey(caseId: string): string {
  return `nyayarag.workspace.saved_answers.${caseId}`;
}

export const demoWorkspaceContext: WorkspaceCaseContext = {
  case_id: "demo-bail-001",
  appellant_petitioner: "Arjun Rao",
  respondent_opposite_party: "State of Karnataka",
  advocates: ["Mohan Ganesh", "A. Priya"],
  case_type: "criminal",
  court: "High Court of Karnataka",
  case_number: "Criminal Petition No. 4812/2026",
  stage: "bail",
  charges_sections: ["IPC 420", "IPC 406", "CrPC 438"],
  bnss_equivalents: ["BNS 318", "BNS 316", "BNSS 482"],
  statutes_involved: [
    "Bharatiya Nagarik Suraksha Sanhita, 2023",
    "Bharatiya Nyaya Sanhita, 2023",
    "Information Technology Act, 2000",
  ],
  key_facts: [
    {
      date: "2026-02-14",
      label: "FIR registered",
      detail: "Complaint alleges inducement, transfer of funds, and non-delivery of contracted software services.",
    },
    {
      date: "2026-02-18",
      label: "Notice of appearance",
      detail: "Investigating officer directed the accused to appear and produce account statements.",
    },
    {
      date: "2026-03-02",
      label: "Anticipatory bail urgency",
      detail: "Client fears arrest after custodial interrogation note appears in the case diary extract.",
    },
  ],
  previous_orders: [
    {
      court: "LXVI Additional City Civil and Sessions Court, Bengaluru",
      date: "2026-03-05",
      outcome: "Interim protection denied pending detailed hearing.",
    },
  ],
  bail_history: [
    {
      court: "Sessions Court, Bengaluru",
      date: "2026-03-05",
      outcome: "Interim protection denied; matter adjourned for records.",
    },
  ],
  open_legal_issues: [
    "Whether the dispute is predominantly civil despite cheating allegations.",
    "Whether custodial interrogation is genuinely necessary.",
    "Whether cooperation and document production satisfy the anticipatory bail threshold.",
  ],
  uploaded_docs: [
    {
      name: "FIR_2026_214.pdf",
      document_type: "FIR",
      pages: 6,
      confidence: 0.97,
    },
    {
      name: "Charge_Summary_Draft.docx",
      document_type: "draft_note",
      pages: 4,
      confidence: 0.99,
    },
    {
      name: "Sessions_Order_Scan.pdf",
      document_type: "court_order",
      pages: 8,
      confidence: 0.82,
    },
  ],
  doc_extraction_confidence: 0.93,
};
