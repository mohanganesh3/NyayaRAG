import { BootstrapQueryConsole } from "../research/BootstrapQueryConsole";
import {
  CitationBadge,
  MetricPill,
  SectionLabel,
  SurfaceCard,
} from "../design";
import type { WorkspaceCaseContext } from "../../lib/workspace";

type WorkspaceShellProps = {
  context: WorkspaceCaseContext;
};

const suggestedQueries = [
  "What are the strongest anticipatory bail arguments on these facts?",
  "Which Supreme Court authorities support treating this as a civil dispute?",
  "What weaknesses will the prosecution press in reply?",
];

const sourceViewerPreview = {
  citation: "Siddharam Satlingappa Mhetre v State of Maharashtra, (2011) 1 SCC 694",
  court: "Supreme Court of India",
  note: "Binding anticipatory bail authority",
  excerpt:
    "Personal liberty under Article 21 requires courts to apply anticipatory bail principles with care, especially where custody is sought without concrete investigative necessity.",
  linkedAuthorities: [
    "Arnesh Kumar v State of Bihar, (2014) 8 SCC 273",
    "Gurbaksh Singh Sibbia v State of Punjab, (1980) 2 SCC 565",
  ],
};

function toTitleCase(value: string | null): string {
  if (!value) {
    return "Not set";
  }

  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function WorkspaceShell({ context }: WorkspaceShellProps) {
  const defaultWorkspaceQuery =
    "What are the strongest anticipatory bail arguments on these facts, and which binding Supreme Court cases should appear first in the note?";

  return (
    <div className="grid gap-4 xl:grid-cols-[19rem_minmax(0,1fr)_20rem] xl:items-start">
      <div className="space-y-4 xl:sticky xl:top-6">
        <SurfaceCard className="p-5" tone="paper">
          <SectionLabel>Case context</SectionLabel>
          <h1 className="mt-3 text-3xl text-ink-950">
            {context.appellant_petitioner} v. {context.respondent_opposite_party}
          </h1>
          <p className="mt-3 text-sm leading-7 text-ink-700">
            {context.case_number} · {context.court}
          </p>

          <div className="mt-5 grid gap-3">
            <MetricPill
              className="w-full"
              label="Case type"
              tone="ink"
              value={toTitleCase(context.case_type)}
            />
            <MetricPill
              className="w-full"
              label="Current stage"
              tone="brass"
              value={toTitleCase(context.stage)}
            />
            <MetricPill
              className="w-full"
              label="Extraction confidence"
              tone="teal"
              value={`${Math.round(context.doc_extraction_confidence * 100)}%`}
            />
          </div>

          <div className="mt-6 space-y-5">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.22em] text-ink-700">
                Advocates
              </p>
              <ul className="mt-3 space-y-2 text-sm leading-7 text-ink-800">
                {context.advocates.map((advocate) => (
                  <li
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/70 px-3 py-2"
                    key={advocate}
                  >
                    {advocate}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="font-mono text-xs uppercase tracking-[0.22em] text-ink-700">
                Uploaded documents
              </p>
              <div className="mt-3 space-y-3">
                {context.uploaded_docs.map((document) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 px-3 py-3"
                    key={document.name}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-ink-950">
                          {document.name}
                        </p>
                        <p className="mt-1 text-xs uppercase tracking-[0.18em] text-ink-700">
                          {document.document_type} · {document.pages} pages
                        </p>
                      </div>
                      <CitationBadge tone="verified">
                        {Math.round(document.confidence * 100)}%
                      </CitationBadge>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </SurfaceCard>

        <SurfaceCard className="p-5" tone="muted">
          <SectionLabel>Open issues</SectionLabel>
          <ul className="mt-4 space-y-3 text-sm leading-7 text-ink-800">
            {context.open_legal_issues.map((issue) => (
              <li
                className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/75 px-3 py-3"
                key={issue}
              >
                {issue}
              </li>
            ))}
          </ul>
        </SurfaceCard>
      </div>

      <div className="space-y-4">
        <SurfaceCard className="p-6 sm:p-7" tone="paper">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-3">
              <SectionLabel>Research workbench</SectionLabel>
              <h2 className="text-3xl text-ink-950">
                Ask a grounded question against this case file.
              </h2>
              <p className="max-w-3xl text-sm leading-7 text-ink-700">
                The shell is now ready for real research flow: case context on
                the left, query and answer path in the center, source evidence
                on the right.
              </p>
            </div>
            <CitationBadge tone="binding">Workspace ready</CitationBadge>
          </div>

          <div className="mt-6 flex flex-wrap gap-2">
            {context.charges_sections.map((section) => (
              <CitationBadge key={section} tone="uncertain">
                {section}
              </CitationBadge>
            ))}
            {context.bnss_equivalents.map((section) => (
              <CitationBadge key={section} tone="verified">
                {section}
              </CitationBadge>
            ))}
          </div>
        </SurfaceCard>

        <BootstrapQueryConsole
          buttonLabel="Start Research"
          defaultQuery={defaultWorkspaceQuery}
          description="Submit a live query from the workspace and watch ordered backend steps resolve into an answer stream. The same SSE contract now powers the actual center lane."
          heading="Live process display for workspace research."
          sectionLabel="Live research display"
          showContractNotes={false}
          showQueryInput
          suggestedQueries={suggestedQueries}
        />

        <SurfaceCard className="p-5" tone="muted">
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <SectionLabel>Facts timeline</SectionLabel>
              <div className="mt-4 space-y-3">
                {context.key_facts.map((fact) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/75 px-4 py-3"
                    key={`${fact.date}-${fact.label}`}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.2em] text-ink-700">
                      {fact.date ?? "Undated"}
                    </p>
                    <p className="mt-2 text-sm font-semibold text-ink-950">
                      {fact.label}
                    </p>
                    <p className="mt-2 text-sm leading-7 text-ink-800">
                      {fact.detail}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <SectionLabel>Prior orders</SectionLabel>
              <div className="mt-4 space-y-3">
                {[...context.previous_orders, ...context.bail_history].map((order) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/75 px-4 py-3"
                    key={`${order.court}-${order.date}-${order.outcome}`}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.2em] text-ink-700">
                      {order.date ?? "Undated"} · {order.court}
                    </p>
                    <p className="mt-2 text-sm leading-7 text-ink-800">
                      {order.outcome}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </SurfaceCard>
      </div>

      <div className="space-y-4 xl:sticky xl:top-6">
        <SurfaceCard className="p-5" tone="ink">
          <div className="flex items-start justify-between gap-3">
            <div>
              <SectionLabel className="text-[rgba(244,236,221,0.72)]">
                Source viewer
              </SectionLabel>
              <h2 className="mt-3 text-2xl text-paper-50">
                Primary authority stays open while you research.
              </h2>
            </div>
            <CitationBadge tone="binding">Binding</CitationBadge>
          </div>

          <div className="mt-5 rounded-[1.2rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.06)] p-4">
            <p className="font-serif text-xl text-paper-50">
              {sourceViewerPreview.citation}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <CitationBadge tone="verified">Verified</CitationBadge>
              <CitationBadge tone="binding">{sourceViewerPreview.court}</CitationBadge>
            </div>
            <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.78)]">
              {sourceViewerPreview.note}
            </p>
          </div>

          <div className="mt-4 rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] p-4">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(244,236,221,0.6)]">
              Relevant passage
            </p>
            <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.84)]">
              {sourceViewerPreview.excerpt}
            </p>
          </div>

          <div className="mt-5">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(244,236,221,0.6)]">
              Linked authorities
            </p>
            <ul className="mt-3 space-y-3 text-sm leading-7 text-[rgba(252,247,239,0.82)]">
              {sourceViewerPreview.linkedAuthorities.map((authority) => (
                <li
                  className="rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] px-3 py-3"
                  key={authority}
                >
                  {authority}
                </li>
              ))}
            </ul>
          </div>
        </SurfaceCard>

        <SurfaceCard className="p-5" tone="paper">
          <SectionLabel>Acts in play</SectionLabel>
          <div className="mt-4 flex flex-wrap gap-2">
            {context.statutes_involved.map((statute) => (
              <CitationBadge key={statute} tone="persuasive">
                {statute}
              </CitationBadge>
            ))}
          </div>
        </SurfaceCard>
      </div>
    </div>
  );
}
