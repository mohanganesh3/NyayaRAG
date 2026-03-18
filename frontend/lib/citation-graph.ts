import {
  buildStructuredSourceId,
  collectStructuredAnswerSources,
  type StructuredAnswer,
  type StructuredAnswerBadgeStatus,
  type StructuredAnswerSource,
} from "./structured-answer";

export type CitationGraphNodeKind = "query" | "section" | "source";

export type CitationGraphNode = {
  height: number;
  id: string;
  kind: CitationGraphNodeKind;
  label: string;
  metadata: string | null;
  source: StructuredAnswerSource | null;
  status: StructuredAnswerBadgeStatus | null;
  width: number;
  x: number;
  y: number;
};

export type CitationGraphEdge = {
  active: boolean;
  from: string;
  id: string;
  to: string;
};

export type CitationGraphModel = {
  edges: CitationGraphEdge[];
  height: number;
  nodes: CitationGraphNode[];
  width: number;
};

function distributePositions(count: number, start: number, end: number): number[] {
  if (count <= 1) {
    return [(start + end) / 2];
  }

  const gap = (end - start) / (count - 1);
  return Array.from({ length: count }, (_, index) => start + gap * index);
}

export function buildCitationGraph(
  answer: StructuredAnswer,
  activeSourceId: string | null,
): CitationGraphModel {
  const sections = answer.sections.filter((section) =>
    section.claims.some((claim) =>
      claim.citationBadges.some((badge) => badge.citation || badge.sourcePassage),
    ),
  );
  const sources = collectStructuredAnswerSources(answer);
  const width = 760;
  const height = Math.max(420, 200 + Math.max(sections.length, sources.length) * 86);
  const sectionYs = distributePositions(
    Math.max(sections.length, 1),
    72,
    Math.max(height - 122, 72),
  );
  const sourceYs = distributePositions(
    Math.max(sources.length, 1),
    56,
    Math.max(height - 110, 56),
  );

  const nodes: CitationGraphNode[] = [
    {
      id: "query-root",
      kind: "query",
      label: "Research query",
      metadata: answer.query,
      source: null,
      status: answer.overallStatus,
      width: 188,
      height: 96,
      x: 38,
      y: height / 2 - 48,
    },
  ];

  const edges: CitationGraphEdge[] = [];
  const sectionSourceMap = new Map<string, Set<string>>();

  sections.forEach((section) => {
    sectionSourceMap.set(section.kind, new Set<string>());
    for (const claim of section.claims) {
      for (const badge of claim.citationBadges) {
        if (!badge.citation && !badge.sourcePassage) {
          continue;
        }

        sectionSourceMap
          .get(section.kind)
          ?.add(
            buildStructuredSourceId({
              docId: badge.docId,
              chunkId: badge.chunkId,
              citation: badge.citation,
              label: badge.label,
            }),
          );
      }
    }
  });

  sections.forEach((section, index) => {
    const sectionId = `section-${section.kind}`;
    const linkedSourceIds = sectionSourceMap.get(section.kind) ?? new Set<string>();

    nodes.push({
      id: sectionId,
      kind: "section",
      label: section.title,
      metadata: `${linkedSourceIds.size} cited authorities`,
      source: null,
      status: section.claims.some((claim) => claim.status === "UNCERTAIN")
        ? "UNCERTAIN"
        : section.claims.some((claim) => claim.status === "UNVERIFIED")
          ? "UNVERIFIED"
          : "VERIFIED",
      width: 170,
      height: 82,
      x: 284,
      y: sectionYs[index] ?? sectionYs[0],
    });

    edges.push({
      id: `query-to-${sectionId}`,
      from: "query-root",
      to: sectionId,
      active: linkedSourceIds.has(activeSourceId ?? ""),
    });
  });

  sources.forEach((source, index) => {
    nodes.push({
      id: source.id,
      kind: "source",
      label: source.label,
      metadata: source.docId,
      source,
      status: source.status,
      width: 190,
      height: 92,
      x: 522,
      y: sourceYs[index] ?? sourceYs[0],
    });
  });

  for (const section of sections) {
    const sectionId = `section-${section.kind}`;
    const sourceIds = sectionSourceMap.get(section.kind) ?? new Set<string>();

    for (const sourceId of sourceIds) {
      edges.push({
        id: `${sectionId}-to-${sourceId}`,
        from: sectionId,
        to: sourceId,
        active: sourceId === activeSourceId,
      });
    }
  }

  return {
    width,
    height,
    nodes,
    edges,
  };
}
