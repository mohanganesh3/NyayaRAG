"use client";

import { useEffect, useReducer, useRef, useState } from "react";

import {
  CitationBadge,
  MetricPill,
  ProcessPanel,
  SectionLabel,
  SurfaceCard,
} from "../design";
import {
  type QueryStreamAction,
  type ErrorResponse,
  type QueryAcceptedResponse,
  type QueryStreamEvent,
  applyQueryStreamEvent,
  createInitialQueryStreamState,
} from "../../lib/query-stream";

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type BootstrapQueryConsoleProps = {
  buttonLabel?: string;
  description?: string;
  defaultQuery?: string;
  heading?: string;
  sectionLabel?: string;
  showContractNotes?: boolean;
  showQueryInput?: boolean;
  suggestedQueries?: string[];
  workspaceId?: string;
};

export function BootstrapQueryConsole({
  buttonLabel = "Run Stream Demo",
  description = "This dummy query proves the Phase 0 streaming contract: submit a query, receive typed SSE events, and render process steps plus token output on the client.",
  defaultQuery = "Bootstrap streaming contract check",
  heading = "Observe the verification path before the answer lands.",
  sectionLabel = "Streaming Contract Preview",
  showContractNotes = true,
  showQueryInput = false,
  suggestedQueries = [],
  workspaceId,
}: BootstrapQueryConsoleProps = {}) {
  const [state, dispatch] = useReducer(
    (
      currentState: ReturnType<typeof createInitialQueryStreamState>,
      action: QueryStreamAction,
    ) => applyQueryStreamEvent(currentState, action),
    undefined,
    createInitialQueryStreamState,
  );
  const [queryText, setQueryText] = useState(defaultQuery);
  const [requestError, setRequestError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useEffect(() => {
    setQueryText(defaultQuery);
  }, [defaultQuery]);

  async function runStreamDemo() {
    eventSourceRef.current?.close();
    setRequestError(null);
    dispatch({ type: "RESET" });
    dispatch({
      type: "STEP_START",
      step: "Connecting to backend...",
      sequence: 0,
      emitted_at: new Date().toISOString(),
    });

    const response = await fetch(`${apiBaseUrl}/api/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(
        workspaceId
          ? {
              query: queryText,
              workspace_id: workspaceId,
            }
          : {
              query: queryText,
            },
      ),
    });

    if (!response.ok) {
      const errorPayload = (await response.json()) as ErrorResponse;
      setRequestError(errorPayload.error.message);
      dispatch({
        type: "STEP_ERROR",
        step: "Connecting to backend...",
        error: errorPayload.error.message,
        sequence: 0,
        emitted_at: new Date().toISOString(),
      });
      return;
    }

    const accepted = (await response.json()) as QueryAcceptedResponse;
    dispatch({
      type: "STEP_COMPLETE",
      step: "Connecting to backend...",
      data: {
        query_id: accepted.data.query_id,
        stream_url: accepted.data.stream_url,
      },
      sequence: 0,
      emitted_at: new Date().toISOString(),
    });

    const streamUrl = `${apiBaseUrl}${accepted.data.stream_url}`;
    const source = new EventSource(streamUrl);
    eventSourceRef.current = source;

    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as QueryStreamEvent;
      dispatch(event);
      if (event.type === "COMPLETE" || event.type === "STEP_ERROR") {
        source.close();
      }
    };

    source.onerror = () => {
      setRequestError("Failed to consume the streaming query contract.");
      dispatch({
        type: "STEP_ERROR",
        step: "Streaming response",
        error: "EventSource connection failed.",
        sequence: 0,
        emitted_at: new Date().toISOString(),
      });
      source.close();
    };
  }

  return (
    <SurfaceCard className="p-6 sm:p-7" tone="paper">
      <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-3">
          <SectionLabel>{sectionLabel}</SectionLabel>
          <h2 className="max-w-3xl text-3xl leading-[1.02] text-ink-950">
            {heading}
          </h2>
          <p className="max-w-2xl text-sm leading-7 text-ink-700">
            {description}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <CitationBadge tone="verified">Typed SSE</CitationBadge>
          <CitationBadge tone="binding">Process-first UI</CitationBadge>
          <button
            className="rounded-full border border-[rgba(171,127,40,0.25)] bg-ink-950 px-5 py-3 text-sm font-semibold text-paper-50 shadow-dossier transition hover:-translate-y-0.5 hover:bg-ink-900"
            onClick={() => void runStreamDemo()}
            type="button"
          >
            {buttonLabel}
          </button>
        </div>
      </div>

      {showQueryInput ? (
        <div className="mt-6 rounded-[1.35rem] border border-[rgba(16,32,53,0.1)] bg-white/72 p-4">
          <label
            className="font-mono text-xs uppercase tracking-[0.2em] text-ink-700"
            htmlFor="workspace-query"
          >
            Query input
          </label>
          <textarea
            className="mt-3 min-h-36 w-full rounded-[1.1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50 px-4 py-4 text-sm leading-7 text-ink-900 outline-none transition placeholder:text-ink-700/70 focus:border-[rgba(171,127,40,0.35)] focus:ring-2 focus:ring-[rgba(171,127,40,0.12)]"
            id="workspace-query"
            onChange={(event) => {
              setQueryText(event.target.value);
            }}
            value={queryText}
          />

          {suggestedQueries.length > 0 ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {suggestedQueries.map((query) => (
                <button
                  className="rounded-full border border-[rgba(16,32,53,0.1)] bg-paper-50 px-3 py-2 text-left text-xs font-medium tracking-[0.02em] text-ink-800 transition hover:border-[rgba(171,127,40,0.28)] hover:bg-white"
                  key={query}
                  onClick={() => {
                    setQueryText(query);
                  }}
                  type="button"
                >
                  {query}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-7 grid gap-4 xl:grid-cols-[1.08fr_0.92fr]">
        <ProcessPanel
          emptyMessage="No events yet. Start the demo to inspect the SSE contract."
          eyebrow="Live process"
          steps={state.steps}
          title="Monospace verification timeline"
        />

        <div className="space-y-4">
          <SurfaceCard className="p-5" tone="muted">
            <SectionLabel>Stream status</SectionLabel>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <MetricPill label="Status" tone="ink" value={state.status} />
              <MetricPill
                label="Confidence"
                tone="teal"
                value={
                  state.confidence !== null
                    ? state.confidence.toFixed(2)
                    : "N/A"
                }
              />
            </div>
          </SurfaceCard>

          <SurfaceCard className="p-5" tone="paper">
            <SectionLabel>Answer stream</SectionLabel>
            <div
              className={`mt-4 min-h-24 rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/76 px-4 py-4 text-sm leading-7 text-ink-900 transition-all duration-500 ${
                state.output
                  ? "translate-y-0 opacity-100"
                  : "translate-y-2 opacity-55"
              }`}
            >
              <p aria-live="polite">
                {state.output || "No streamed answer yet. Start the run to watch the response fade in as tokens arrive."}
              </p>
            </div>
          </SurfaceCard>

          {state.agentLogs.length > 0 ? (
            <SurfaceCard className="p-5" tone="paper">
              <SectionLabel>Recent agent activity</SectionLabel>
              <div className="mt-4 space-y-3">
                {state.agentLogs.slice(-3).map((entry, index) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/70 px-3 py-3"
                    key={`${entry.agent}-${index}`}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-ink-700">
                      {entry.agent}
                    </p>
                    <p className="mt-2 text-sm leading-7 text-ink-800">
                      {entry.message}
                    </p>
                  </div>
                ))}
              </div>
            </SurfaceCard>
          ) : null}

          {state.citationResolutions.length > 0 ? (
            <SurfaceCard className="p-5" tone="muted">
              <SectionLabel>Citation resolution</SectionLabel>
              <div className="mt-4 space-y-3">
                {state.citationResolutions.slice(-2).map((resolution) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/75 px-3 py-3"
                    key={`${resolution.placeholder}-${resolution.citation}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <CitationBadge
                        tone={
                          resolution.status === "VERIFIED"
                            ? "verified"
                            : resolution.status === "UNCERTAIN"
                              ? "uncertain"
                              : "unverified"
                        }
                      >
                        {resolution.status}
                      </CitationBadge>
                      <span className="text-xs uppercase tracking-[0.16em] text-ink-700">
                        {resolution.placeholder}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-7 text-ink-800">
                      {resolution.citation}
                    </p>
                  </div>
                ))}
              </div>
            </SurfaceCard>
          ) : null}

          {showContractNotes ? (
            <SurfaceCard className="p-5" tone="paper">
              <SectionLabel>Contract notes</SectionLabel>
              <div className="mt-4 flex flex-wrap gap-2">
                <CitationBadge tone="verified">Step start</CitationBadge>
                <CitationBadge tone="verified">Step complete</CitationBadge>
                <CitationBadge tone="persuasive">Token stream</CitationBadge>
                <CitationBadge tone="binding">Complete</CitationBadge>
              </div>
              <p className="mt-4 text-sm leading-7 text-ink-700">
                The client consumes typed SSE events, orders the process steps,
                and fades the answer stream into view as tokens arrive.
              </p>
            </SurfaceCard>
          ) : null}

          {requestError ? (
            <p className="rounded-2xl border border-[rgba(152,80,77,0.25)] bg-[rgba(255,255,255,0.9)] px-4 py-3 text-sm text-garnet-500 shadow-card">
              {requestError}
            </p>
          ) : null}
        </div>
      </div>
    </SurfaceCard>
  );
}
