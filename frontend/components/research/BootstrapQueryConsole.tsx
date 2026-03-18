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
  type ErrorResponse,
  type QueryAcceptedResponse,
  type QueryStreamEvent,
  applyQueryStreamEvent,
  createInitialQueryStreamState,
} from "../../lib/query-stream";

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function BootstrapQueryConsole() {
  const [state, dispatch] = useReducer(
    applyQueryStreamEvent,
    undefined,
    createInitialQueryStreamState,
  );
  const [requestError, setRequestError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  async function runStreamDemo() {
    eventSourceRef.current?.close();
    setRequestError(null);
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
      body: JSON.stringify({
        query: "Bootstrap streaming contract check",
      }),
    });

    if (!response.ok) {
      const errorPayload = (await response.json()) as ErrorResponse;
      setRequestError(errorPayload.error.message);
      return;
    }

    const accepted = (await response.json()) as QueryAcceptedResponse;
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
      source.close();
    };
  }

  return (
    <SurfaceCard className="p-6 sm:p-7" tone="paper">
      <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-3">
          <SectionLabel>Streaming Contract Preview</SectionLabel>
          <h2 className="max-w-3xl text-3xl leading-[1.02] text-ink-950">
            Observe the verification path before the answer lands.
          </h2>
          <p className="max-w-2xl text-sm leading-7 text-ink-700">
            This dummy query proves the Phase 0 streaming contract: submit a
            query, receive typed SSE events, and render process steps plus token
            output on the client.
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
            Run Stream Demo
          </button>
        </div>
      </div>

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
            <SectionLabel>Token output</SectionLabel>
            <p className="mt-4 min-h-24 text-sm leading-7 text-ink-900">
              {state.output || "No streamed tokens yet."}
            </p>
          </SurfaceCard>

          <SurfaceCard className="p-5" tone="paper">
            <SectionLabel>Contract notes</SectionLabel>
            <div className="mt-4 flex flex-wrap gap-2">
              <CitationBadge tone="verified">Step start</CitationBadge>
              <CitationBadge tone="verified">Step complete</CitationBadge>
              <CitationBadge tone="persuasive">Token stream</CitationBadge>
              <CitationBadge tone="binding">Complete</CitationBadge>
            </div>
            <p className="mt-4 text-sm leading-7 text-ink-700">
              The current client consumes typed SSE events and renders a legal
              research process view first. Answer rendering, source linking, and
              trust summaries will layer on top of this contract in later units.
            </p>
          </SurfaceCard>

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
