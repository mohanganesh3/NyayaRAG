"use client";

import { CitationBadge, SectionLabel, SurfaceCard } from "../design";
import { buildCitationGraph } from "../../lib/citation-graph";
import type {
  StructuredAnswer,
  StructuredAnswerBadgeStatus,
  StructuredAnswerSource,
} from "../../lib/structured-answer";

type CitationGraphProps = {
  activeSourceId: string | null;
  answer: StructuredAnswer;
  onSelectSource: (source: StructuredAnswerSource) => void;
};

function toneForStatus(
  status: StructuredAnswerBadgeStatus | null,
): "verified" | "uncertain" | "unverified" | "binding" {
  if (status === "VERIFIED") {
    return "verified";
  }
  if (status === "UNCERTAIN") {
    return "uncertain";
  }
  if (status === "UNVERIFIED") {
    return "unverified";
  }
  return "binding";
}

function edgeColor(active: boolean): string {
  return active ? "rgba(171,127,40,0.9)" : "rgba(16,32,53,0.16)";
}

export function CitationGraph({
  activeSourceId,
  answer,
  onSelectSource,
}: CitationGraphProps) {
  const graph = buildCitationGraph(answer, activeSourceId);
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));

  return (
    <SurfaceCard className="p-6 sm:p-7" tone="paper">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <SectionLabel>Citation graph</SectionLabel>
          <h2 className="text-3xl text-ink-950">
            Section-level reasoning linked back to cited authorities.
          </h2>
          <p className="max-w-3xl text-sm leading-7 text-ink-700">
            The query anchors the answer sections, and each cited authority
            remains clickable as a graph node. Selecting a node updates the
            evidence panel on the right.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <CitationBadge tone="binding">Query</CitationBadge>
          <CitationBadge tone="persuasive">Section</CitationBadge>
          <CitationBadge tone="verified">Authority</CitationBadge>
        </div>
      </div>

      <div className="mt-6 overflow-x-auto rounded-[1.35rem] border border-[rgba(16,32,53,0.08)] bg-white/68 p-4">
        <div
          className="relative"
          style={{
            height: `${graph.height}px`,
            width: `${graph.width}px`,
          }}
        >
          <svg
            aria-hidden="true"
            className="absolute inset-0 h-full w-full"
            viewBox={`0 0 ${graph.width} ${graph.height}`}
          >
            {graph.edges.map((edge) => {
              const fromNode = nodesById.get(edge.from);
              const toNode = nodesById.get(edge.to);

              if (!fromNode || !toNode) {
                return null;
              }

              return (
                <line
                  key={edge.id}
                  stroke={edgeColor(edge.active)}
                  strokeDasharray={fromNode.kind === "query" ? "0" : "4 8"}
                  strokeLinecap="round"
                  strokeWidth={edge.active ? 3 : 2}
                  x1={fromNode.x + fromNode.width}
                  x2={toNode.x}
                  y1={fromNode.y + fromNode.height / 2}
                  y2={toNode.y + toNode.height / 2}
                />
              );
            })}
          </svg>

          {graph.nodes.map((node) => {
            const isActive = node.id === activeSourceId;
            const baseClassName =
              "absolute rounded-[1.2rem] border shadow-card backdrop-blur transition";
            const style = {
              height: `${node.height}px`,
              left: `${node.x}px`,
              top: `${node.y}px`,
              width: `${node.width}px`,
            };

            if (node.kind === "query") {
              return (
                <div
                  className={`${baseClassName} border-[rgba(231,216,188,0.12)] bg-ink-950 px-4 py-4 text-paper-50`}
                  key={node.id}
                  style={style}
                >
                  <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[rgba(244,236,221,0.6)]">
                    Query root
                  </p>
                  <p className="mt-3 text-lg font-semibold leading-7 text-paper-50">
                    {node.label}
                  </p>
                  <p className="mt-2 line-clamp-3 text-sm leading-6 text-[rgba(252,247,239,0.78)]">
                    {node.metadata}
                  </p>
                </div>
              );
            }

            if (node.kind === "section") {
              return (
                <div
                  className={`${baseClassName} border-[rgba(16,32,53,0.09)] bg-paper-50/88 px-4 py-4 text-ink-950`}
                  key={node.id}
                  style={style}
                >
                  <CitationBadge tone={toneForStatus(node.status)}>
                    {node.status ?? "SECTION"}
                  </CitationBadge>
                  <p className="mt-3 text-sm font-semibold leading-6 text-ink-950">
                    {node.label}
                  </p>
                  <p className="mt-2 text-xs uppercase tracking-[0.14em] text-ink-700">
                    {node.metadata}
                  </p>
                </div>
              );
            }

            return (
              <button
                aria-label={`Citation graph node ${node.label}`}
                className={`${baseClassName} border-[rgba(16,32,53,0.08)] bg-white/92 px-4 py-4 text-left text-ink-950 hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)] ${
                  isActive
                    ? "ring-2 ring-[rgba(171,127,40,0.28)] ring-offset-2 ring-offset-[rgba(252,247,239,0.9)]"
                    : ""
                }`}
                key={node.id}
                onClick={() => {
                  if (node.source) {
                    onSelectSource(node.source);
                  }
                }}
                style={style}
                type="button"
              >
                <div className="flex items-start justify-between gap-3">
                  <CitationBadge tone={toneForStatus(node.status)}>
                    {node.status ?? "SOURCE"}
                  </CitationBadge>
                  {node.metadata ? (
                    <span className="font-mono text-[0.64rem] uppercase tracking-[0.12em] text-ink-700">
                      {node.metadata}
                    </span>
                  ) : null}
                </div>
                <p className="mt-3 text-sm font-semibold leading-6 text-ink-950">
                  {node.label}
                </p>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-ink-700">
                  {node.source?.message}
                </p>
              </button>
            );
          })}
        </div>
      </div>
    </SurfaceCard>
  );
}
