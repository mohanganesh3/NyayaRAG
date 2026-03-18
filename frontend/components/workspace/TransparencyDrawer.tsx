"use client";

import { CitationBadge, MetricPill, SectionLabel } from "../design";
import type { QueryStreamState } from "../../lib/query-stream";

type TransparencyDrawerProps = {
  isOpen: boolean;
  onClose: () => void;
  streamState: QueryStreamState;
};

function toneForResolution(
  status: string,
): "verified" | "uncertain" | "unverified" {
  if (status === "VERIFIED") {
    return "verified";
  }
  if (status === "UNCERTAIN") {
    return "uncertain";
  }
  return "unverified";
}

export function TransparencyDrawer({
  isOpen,
  onClose,
  streamState,
}: TransparencyDrawerProps) {
  const metricEntries = Object.entries(streamState.metrics ?? {});
  const eventCount =
    streamState.steps.length +
    streamState.agentLogs.length +
    streamState.citationResolutions.length;

  return (
    <>
      <button
        aria-hidden={!isOpen}
        className={`fixed inset-0 z-40 bg-[rgba(8,16,28,0.45)] transition ${
          isOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
        tabIndex={isOpen ? 0 : -1}
        type="button"
      />

      <aside
        aria-hidden={!isOpen}
        aria-label="Agent transparency drawer"
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-xl transform flex-col border-l border-[rgba(231,216,188,0.12)] bg-ink-950 text-paper-50 shadow-panel transition-transform duration-300 ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        role="dialog"
      >
        <div className="flex items-start justify-between gap-4 border-b border-[rgba(231,216,188,0.12)] px-6 py-5">
          <div className="space-y-3">
            <SectionLabel className="text-[rgba(244,236,221,0.72)]">
              Transparency log
            </SectionLabel>
            <h2 className="text-3xl text-paper-50">
              Inspect the live backend trace behind the answer.
            </h2>
            <p className="max-w-md text-sm leading-7 text-[rgba(252,247,239,0.76)]">
              This drawer mirrors the actual SSE activity: agent logs, citation
              resolutions, and completion metrics.
            </p>
          </div>

          <button
            className="rounded-full border border-[rgba(244,236,221,0.14)] bg-[rgba(252,247,239,0.04)] px-4 py-2 text-sm font-semibold text-paper-50 transition hover:border-[rgba(207,177,112,0.32)]"
            onClick={onClose}
            type="button"
          >
            Close
          </button>
        </div>

        <div className="grid gap-3 border-b border-[rgba(231,216,188,0.12)] px-6 py-5 sm:grid-cols-3">
          <MetricPill label="Status" tone="ink" value={streamState.status} />
          <MetricPill label="Events" tone="brass" value={`${eventCount}`} />
          <MetricPill
            label="Confidence"
            tone="teal"
            value={
              streamState.confidence !== null
                ? streamState.confidence.toFixed(2)
                : "N/A"
            }
          />
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-6">
          <section>
            <SectionLabel className="text-[rgba(244,236,221,0.72)]">
              Agent activity
            </SectionLabel>
            {streamState.agentLogs.length === 0 ? (
              <p className="mt-4 rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] px-4 py-4 text-sm leading-7 text-[rgba(252,247,239,0.72)]">
                No backend events yet. Run the workspace query to inspect the
                live agent trace.
              </p>
            ) : (
              <div className="mt-4 space-y-3">
                {streamState.agentLogs.map((entry) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] px-4 py-4"
                    key={`${entry.sequence}-${entry.agent}`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-mono text-[0.68rem] uppercase tracking-[0.2em] text-[rgba(244,236,221,0.62)]">
                        {entry.agent}
                      </p>
                      <span className="font-mono text-[0.68rem] uppercase tracking-[0.16em] text-[rgba(244,236,221,0.46)]">
                        #{entry.sequence}
                      </span>
                    </div>
                    <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.82)]">
                      {entry.message}
                    </p>
                    <p className="mt-2 text-xs uppercase tracking-[0.14em] text-[rgba(244,236,221,0.44)]">
                      {entry.emittedAt}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <SectionLabel className="text-[rgba(244,236,221,0.72)]">
              Citation resolution
            </SectionLabel>
            {streamState.citationResolutions.length === 0 ? (
              <p className="mt-4 rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] px-4 py-4 text-sm leading-7 text-[rgba(252,247,239,0.72)]">
                No citation placeholders have been resolved yet.
              </p>
            ) : (
              <div className="mt-4 space-y-3">
                {streamState.citationResolutions.map((resolution) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] px-4 py-4"
                    key={`${resolution.sequence}-${resolution.placeholder}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <CitationBadge tone={toneForResolution(resolution.status)}>
                        {resolution.status}
                      </CitationBadge>
                      <span className="font-mono text-[0.68rem] uppercase tracking-[0.16em] text-[rgba(244,236,221,0.58)]">
                        {resolution.placeholder}
                      </span>
                    </div>
                    <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.84)]">
                      {resolution.citation}
                    </p>
                    <p className="mt-2 text-xs uppercase tracking-[0.14em] text-[rgba(244,236,221,0.44)]">
                      {resolution.emittedAt}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <SectionLabel className="text-[rgba(244,236,221,0.72)]">
              Completion metrics
            </SectionLabel>
            {metricEntries.length === 0 ? (
              <p className="mt-4 rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] px-4 py-4 text-sm leading-7 text-[rgba(252,247,239,0.72)]">
                No completion payload yet. Metrics appear after the stream
                finishes.
              </p>
            ) : (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {metricEntries.map(([key, value]) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] px-4 py-4"
                    key={key}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.2em] text-[rgba(244,236,221,0.58)]">
                      {key}
                    </p>
                    <p className="mt-3 text-lg leading-7 text-paper-50">
                      {String(value)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}
