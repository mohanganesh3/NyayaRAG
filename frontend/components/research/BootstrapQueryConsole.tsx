"use client";

import { useEffect, useReducer, useRef, useState } from "react";

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
    <section className="rounded-2xl border border-navy-800/20 bg-white p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <h2 className="font-serif text-2xl text-navy-900">
            Streaming Contract Preview
          </h2>
          <p className="max-w-2xl text-sm leading-6 text-text-secondary">
            This dummy query proves the Phase 0 streaming contract: submit a
            query, receive typed SSE events, and render process steps plus token
            output on the client.
          </p>
        </div>
        <button
          className="rounded-full bg-teal-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-navy-900"
          onClick={() => void runStreamDemo()}
          type="button"
        >
          Run Stream Demo
        </button>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-xl bg-navy-900 p-5 text-cream-50">
          <p className="font-mono text-xs uppercase tracking-[0.25em] text-gold-400">
            Live Process
          </p>
          <div className="mt-4 space-y-3 font-mono text-sm">
            {state.steps.length === 0 ? (
              <p className="text-cream-100/80">
                No events yet. Start the demo to inspect the SSE contract.
              </p>
            ) : null}
            {state.steps.map((step) => (
              <div key={`${step.name}-${step.status}`} className="space-y-1">
                <p>
                  {step.status === "running" ? "[●]" : null}
                  {step.status === "completed" ? "[✓]" : null}
                  {step.status === "error" ? "[✗]" : null} {step.name}
                </p>
                {step.detail ? (
                  <p className="pl-7 text-xs text-cream-100/70">{step.detail}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4 rounded-xl border border-gold-400/30 bg-cream-100 p-5">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.25em] text-text-secondary">
              Stream Status
            </p>
            <p className="mt-2 font-serif text-2xl text-navy-900">
              {state.status}
            </p>
          </div>
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.25em] text-text-secondary">
              Token Output
            </p>
            <p className="mt-2 min-h-16 text-sm leading-7 text-text-primary">
              {state.output || "No streamed tokens yet."}
            </p>
          </div>
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.25em] text-text-secondary">
              Confidence
            </p>
            <p className="mt-2 text-sm text-text-primary">
              {state.confidence !== null ? state.confidence.toFixed(2) : "N/A"}
            </p>
          </div>
          {requestError ? (
            <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {requestError}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
