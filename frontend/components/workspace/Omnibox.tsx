"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { CitationBadge, SurfaceCard } from "../design";
import {
  type QueryStreamAction,
  type ErrorResponse,
  type QueryAcceptedResponse,
  type QueryStreamEvent,
  type QueryStreamState,
  applyQueryStreamEvent,
  createInitialQueryStreamState,
} from "../../lib/query-stream";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type OmniboxProps = {
  defaultQuery?: string;
  suggestedQueries?: string[];
  workspaceId?: string;
  onQuerySubmitted?: (queryText: string) => void;
  onStateChange?: (state: QueryStreamState) => void;
  requestHeaders?: Record<string, string>;
};

export function Omnibox({
  defaultQuery = "",
  suggestedQueries = [],
  workspaceId,
  onQuerySubmitted,
  onStateChange,
  requestHeaders,
}: OmniboxProps) {
  const [state, dispatch] = useReducer(
    (currentState: ReturnType<typeof createInitialQueryStreamState>, action: QueryStreamAction) =>
      applyQueryStreamEvent(currentState, action),
    undefined,
    createInitialQueryStreamState
  );
  const [queryText, setQueryText] = useState(defaultQuery);
  const [isFocused, setIsFocused] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useEffect(() => {
    onStateChange?.(state);
    if (state.status === "complete" || state.status === "error") {
      setIsStreaming(false);
    }
  }, [onStateChange, state]);

  async function submitQuery() {
    if (!queryText.trim() || isStreaming) return;

    setIsStreaming(true);
    eventSourceRef.current?.close();
    setRequestError(null);
    onQuerySubmitted?.(queryText);
    dispatch({ type: "RESET" });
    dispatch({
      type: "STEP_START",
      step: "Initializing Hybrid RAG Pipeline...",
      sequence: 0,
      emitted_at: new Date().toISOString(),
    });

    try {
      const response = await fetch(`${apiBaseUrl}/api/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...requestHeaders,
        },
        body: JSON.stringify(
          workspaceId
            ? { query: queryText, workspace_id: workspaceId }
            : { query: queryText }
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
        setIsStreaming(false);
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
          setIsStreaming(false);
        }
      };

      source.onerror = () => {
        setRequestError("EventSource connection failed.");
        dispatch({
          type: "STEP_ERROR",
          step: "Streaming response",
          error: "Connection lost.",
          sequence: 0,
          emitted_at: new Date().toISOString(),
        });
        source.close();
        setIsStreaming(false);
      };
    } catch (err) {
      setRequestError("Network error. Please try again.");
      setIsStreaming(false);
    }
  }

  return (
    <SurfaceCard 
      className={`relative overflow-hidden transition-all duration-500 ${
        isFocused ? "shadow-panel border-[rgba(171,127,40,0.4)]" : "border-[rgba(16,32,53,0.1)]"
      }`} 
      tone="ink"
    >
      {/* Background glow effect when focused */}
      <div 
        className={`absolute inset-0 bg-gradient-to-r from-[rgba(171,127,40,0.05)] to-[rgba(27,116,105,0.05)] transition-opacity duration-700 ${
          isFocused ? "opacity-100" : "opacity-0"
        }`}
      />

      <div className="relative p-6 sm:p-8">
        <label className="font-mono text-[0.7rem] uppercase tracking-[0.22em] text-[rgba(244,236,221,0.6)]">
          NyayaRAG Intelligence Query
        </label>
        
        <textarea
          className="mt-4 w-full resize-none bg-transparent text-2xl sm:text-3xl font-light leading-snug text-paper-50 placeholder-[rgba(244,236,221,0.25)] outline-none transition-all duration-300"
          rows={3}
          placeholder="Ask a grounded question against the 11.4M document Indian legal corpus..."
          value={queryText}
          onChange={(e) => setQueryText(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submitQuery();
            }
          }}
        />

        <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-[rgba(244,236,221,0.1)] pt-5">
          <div className="flex flex-wrap gap-2 max-w-2xl">
            {suggestedQueries.map((query) => (
              <button
                key={query}
                className="rounded-full border border-[rgba(244,236,221,0.15)] bg-[rgba(244,236,221,0.03)] px-3 py-1.5 text-xs font-medium tracking-wide text-[rgba(244,236,221,0.7)] transition-colors hover:border-[rgba(171,127,40,0.4)] hover:text-paper-50"
                onClick={() => setQueryText(query)}
                type="button"
              >
                {query}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-3">
            {isStreaming && (
              <CitationBadge tone="persuasive">
                <span className="animate-pulse">Retrieving...</span>
              </CitationBadge>
            )}
            <button
              className={`rounded-full px-6 py-2.5 text-sm font-semibold transition-all duration-300 ${
                !queryText.trim() || isStreaming
                  ? "bg-[rgba(244,236,221,0.1)] text-[rgba(244,236,221,0.4)] cursor-not-allowed"
                  : "bg-brass-500 text-ink-950 shadow-[0_0_20px_rgba(171,127,40,0.3)] hover:bg-brass-300 hover:shadow-[0_0_30px_rgba(171,127,40,0.5)] hover:-translate-y-0.5"
              }`}
              disabled={!queryText.trim() || isStreaming}
              onClick={() => void submitQuery()}
              type="button"
            >
              {isStreaming ? "Synthesizing" : "Execute Query"}
            </button>
          </div>
        </div>

        {requestError && (
          <div className="mt-4 rounded-xl border border-[rgba(152,80,77,0.3)] bg-[rgba(152,80,77,0.1)] p-3 text-sm text-[rgba(242,177,172,0.9)]">
            {requestError}
          </div>
        )}
      </div>
    </SurfaceCard>
  );
}
