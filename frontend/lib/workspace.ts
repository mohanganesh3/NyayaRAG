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
