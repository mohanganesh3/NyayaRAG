import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { FrontendAuthSession } from "../../lib/auth-session";
import { demoQueryHistoryForSession } from "../../lib/query-history";
import { demoWorkspaceContext } from "../../lib/workspace";
import { WorkspaceShell } from "./WorkspaceShell";

function createStorageMock(): Storage {
  const store = new Map<string, string>();

  return {
    clear: () => {
      store.clear();
    },
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
  };
}

describe("WorkspaceShell", () => {
  beforeEach(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: createStorageMock(),
    });
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders persisted case context fields and source viewer content", async () => {
    const authSession: FrontendAuthSession = {
      isAuthenticated: true,
      provider: "dev_header",
      userId: "dev-advocate",
      displayName: "Local Advocate Session",
    };

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes("/api/citation/sc-arnesh-2014/source")) {
        return {
          ok: true,
          json: async () => ({
            success: true,
            data: {
              doc_id: "sc-arnesh-2014",
              effective_doc_id: "sc-arnesh-2014",
              chunk_id: "chunk-2",
              effective_chunk_id: "chunk-2",
              doc_type: "judgment",
              citation: "Arnesh Kumar v State of Bihar, (2014) 8 SCC 273",
              effective_citation: "Arnesh Kumar v State of Bihar, (2014) 8 SCC 273",
              title: "Arnesh Kumar v State of Bihar",
              court: "Supreme Court",
              date: "2014-07-02",
              section_header: "Holding",
              act_name: null,
              section_number: null,
              current_validity: "GOOD_LAW",
              is_in_force: null,
              source_passage:
                "Canonical source viewer fetched from backend: arrest cannot be routine without concrete necessity.",
              source_url: "https://example.test/arnesh-kumar",
              source_system: "supreme_court",
              source_document_ref: "AIR 2014 SC 2756",
              appeal_status: "VALID",
              appeal_severity: "INFO",
              appeal_warning: null,
              path_doc_ids: ["sc-arnesh-2014"],
            },
          }),
        } as Response;
      }
      if (url.includes("/api/citation/bnss-482/source")) {
        return {
          ok: true,
          json: async () => ({
            success: true,
            data: {
              doc_id: "bnss-482",
              effective_doc_id: "bnss-482",
              chunk_id: "section-482",
              effective_chunk_id: "section-482",
              doc_type: "statute",
              citation: "Bharatiya Nagarik Suraksha Sanhita, 2023, Section 482",
              effective_citation:
                "Bharatiya Nagarik Suraksha Sanhita, 2023, Section 482",
              title: "Bharatiya Nagarik Suraksha Sanhita, 2023, Section 482",
              court: "Parliament of India",
              date: "2023-12-25",
              section_header: "Section 482 - Anticipatory bail",
              act_name: "Bharatiya Nagarik Suraksha Sanhita, 2023",
              section_number: "482",
              current_validity: "GOOD_LAW",
              is_in_force: true,
              source_passage:
                "Canonical source viewer fetched from backend: BNSS Section 482 remains the current anticipatory bail provision.",
              source_url: "https://example.test/bnss-482",
              source_system: "indiacode",
              source_document_ref: "BNSS-482",
              appeal_status: "VALID",
              appeal_severity: "INFO",
              appeal_warning: null,
              path_doc_ids: ["bnss-482"],
            },
          }),
        } as Response;
      }
      throw new Error(`Unexpected fetch call in test: ${url}`);
    });

    render(
      <WorkspaceShell
        authHeaders={{ "X-Nyayarag-Dev-User-Id": "dev-advocate" }}
        authSession={authSession}
        context={demoWorkspaceContext}
        queryHistory={demoQueryHistoryForSession(
          authSession,
          demoWorkspaceContext.case_id,
        )}
      />,
    );

    expect(screen.getByText(/Arjun Rao v\. State of Karnataka/i)).toBeInTheDocument();
    expect(screen.getByText(/Criminal Petition No\. 4812\/2026/i)).toBeInTheDocument();
    expect(screen.getByText(/Uploaded documents/i)).toBeInTheDocument();
    expect(screen.getByText(/Upload workspace files/i)).toBeInTheDocument();
    expect(screen.getByText(/Protected workspace/i)).toBeInTheDocument();
    expect(screen.getByText(/dev-advocate/i)).toBeInTheDocument();
    expect(screen.getByText(/Session history/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Saved answers/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Live research display/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open transparency log/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save answer/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export markdown/i })).toBeInTheDocument();
    expect(screen.getByText(/Citation graph/i)).toBeInTheDocument();
    expect(
      screen.getByText(
        /Personal liberty requires the court to examine whether the prosecution has shown concrete investigative necessity before permitting arrest in anticipatory bail matters\./i,
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getAllByRole("button", {
        name: /Arnesh Kumar/i,
      })[0],
    );

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/citation/sc-arnesh-2014/source?chunk_id=chunk-2"),
        expect.any(Object),
      );
      expect(
        screen.getByText(
          /Canonical source viewer fetched from backend: arrest cannot be routine without concrete necessity\./i,
        ),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: /Citation graph node BNSS 482/i,
      }),
    );

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/citation/bnss-482/source?chunk_id=section-482"),
        expect.any(Object),
      );
      expect(
        screen.getByText(
          /Canonical source viewer fetched from backend: BNSS Section 482 remains the current anticipatory bail provision\./i,
        ),
      ).toBeInTheDocument();
    });
  });

  it("processes uploads and saves answers inside the workspace shell", async () => {
    const authSession: FrontendAuthSession = {
      isAuthenticated: true,
      provider: "dev_header",
      userId: "dev-advocate",
      displayName: "Local Advocate Session",
    };

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes("/api/workspace/upload")) {
        return {
          ok: true,
          json: async () => ({
            success: true,
            data: {
              case_id: "demo-bail-001",
              appellant_petitioner: "Arjun Rao",
              respondent_opposite_party: "State of Karnataka",
              advocates: ["Mohan Ganesh"],
              case_type: "criminal",
              court: "High Court of Karnataka",
              case_number: "Criminal Petition No. 4812/2026",
              stage: "bail",
              charges_sections: ["IPC 420", "CrPC 438"],
              bnss_equivalents: ["BNS 318", "BNSS 482"],
              statutes_involved: ["IPC", "CrPC", "BNS", "BNSS"],
              key_facts: [{ label: "FIR registered", detail: "Complaint extracted." }],
              previous_orders: [],
              bail_history: [],
              open_legal_issues: ["Whether anticipatory bail should be granted."],
              uploaded_docs: [
                {
                  name: "uploaded-bundle.docx",
                  document_mode: "docx_text",
                  page_count: 5,
                  confidence: 0.98,
                },
              ],
              doc_extraction_confidence: 0.98,
            },
          }),
        } as Response;
      }
      throw new Error(`Unexpected fetch call in test: ${url}`);
    });

    render(
      <WorkspaceShell
        authHeaders={{ "X-Nyayarag-Dev-User-Id": "dev-advocate" }}
        authSession={authSession}
        context={demoWorkspaceContext}
        queryHistory={demoQueryHistoryForSession(
          authSession,
          demoWorkspaceContext.case_id,
        )}
      />,
    );

    const uploadInput = screen.getByLabelText(
      /Select documents for OCR and context rebuild/i,
    );
    fireEvent.change(uploadInput, {
      target: {
        files: [new File(["draft bail note"], "uploaded-bundle.docx")],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: /Process uploads/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/workspace/upload"),
        expect.objectContaining({ method: "POST" }),
      );
    });
    await waitFor(() => {
      expect(screen.getByText(/uploaded-bundle\.docx/i)).toBeInTheDocument();
      expect(screen.getByText(/Workspace persisted/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Save answer/i }));

    expect(
      screen.getAllByText(/strongest anticipatory bail arguments on these facts/i)
        .length,
    ).toBeGreaterThan(1);
  });
});
