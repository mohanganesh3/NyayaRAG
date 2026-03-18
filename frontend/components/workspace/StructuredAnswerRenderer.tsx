"use client";

import { CitationBadge, SectionLabel, SurfaceCard } from "../design";
import type {
  InlineCitationBadge,
  StructuredAnswer,
  StructuredAnswerBadgeStatus,
  StructuredAnswerSource,
} from "../../lib/structured-answer";
import { buildStructuredSourceId } from "../../lib/structured-answer";

type StructuredAnswerRendererProps = {
  activeSourceId: string | null;
  answer: StructuredAnswer;
  onSelectSource: (source: StructuredAnswerSource) => void;
};

function toneForStatus(
  status: StructuredAnswerBadgeStatus,
): "verified" | "uncertain" | "unverified" {
  if (status === "VERIFIED") {
    return "verified";
  }
  if (status === "UNCERTAIN") {
    return "uncertain";
  }
  return "unverified";
}

function sourceFromBadge(
  badge: InlineCitationBadge,
): StructuredAnswerSource | null {
  if (!badge.citation && !badge.sourcePassage) {
    return null;
  }

  return {
    id: buildStructuredSourceId({
      docId: badge.docId,
      chunkId: badge.chunkId,
      citation: badge.citation,
      label: badge.label,
    }),
    label: badge.label,
    citation: badge.citation ?? badge.label,
    status: badge.status,
    message: badge.message,
    docId: badge.docId,
    chunkId: badge.chunkId,
    sourcePassage: badge.sourcePassage,
    appealWarning: badge.appealWarning,
  };
}

export function StructuredAnswerRenderer({
  activeSourceId,
  answer,
  onSelectSource,
}: StructuredAnswerRendererProps) {
  return (
    <SurfaceCard className="p-6 sm:p-7" tone="paper">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <SectionLabel>Structured answer</SectionLabel>
          <h2 className="text-3xl text-ink-950">
            Verified answer sections, wired to source evidence.
          </h2>
          <p className="max-w-3xl text-sm leading-7 text-ink-700">
            Each claim carries its own verification state. Citation badges open
            the source viewer on hover, focus, or click.
          </p>
        </div>
        <CitationBadge tone={toneForStatus(answer.overallStatus)}>
          {answer.overallStatus}
        </CitationBadge>
      </div>

      <div className="mt-6 space-y-5">
        {answer.sections.map((section) => (
          <div
            className="rounded-[1.35rem] border border-[rgba(16,32,53,0.08)] bg-white/72 p-5"
            key={section.kind}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <SectionLabel>{section.title}</SectionLabel>
                {section.claims.length > 0 ? (
                  <p className="mt-3 text-sm leading-7 text-ink-700">
                    {section.claims.length} grounded claim
                    {section.claims.length > 1 ? "s" : ""}
                  </p>
                ) : null}
              </div>
            </div>

            {section.claims.length > 0 ? (
              <div className="mt-4 space-y-4">
                {section.claims.map((claim) => (
                  <div
                    className="rounded-[1.1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/78 p-4"
                    key={`${section.kind}-${claim.text}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <CitationBadge tone={toneForStatus(claim.status)}>
                        {claim.status}
                      </CitationBadge>
                      {claim.reretrieved ? (
                        <CitationBadge tone="persuasive">Re-retrieved</CitationBadge>
                      ) : null}
                    </div>

                    <p className="mt-3 text-sm leading-7 text-ink-950">
                      {claim.text}
                    </p>

                    {claim.citationBadges.length > 0 ? (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {claim.citationBadges.map((badge) => {
                          const source = sourceFromBadge(badge);
                          const sourceId = source?.id ?? null;
                          const isActive = sourceId !== null && sourceId === activeSourceId;

                          if (source === null) {
                            return (
                              <CitationBadge
                                className="opacity-85"
                                key={`${badge.placeholderToken}-${badge.label}`}
                                tone={toneForStatus(badge.status)}
                              >
                                {badge.label}
                              </CitationBadge>
                            );
                          }

                          return (
                            <button
                              className={`rounded-full transition ${
                                isActive
                                  ? "ring-2 ring-[rgba(171,127,40,0.28)] ring-offset-2 ring-offset-[rgba(252,247,239,0.88)]"
                                  : ""
                              }`}
                              key={`${badge.placeholderToken}-${badge.label}`}
                              onClick={() => {
                                onSelectSource(source);
                              }}
                              onFocus={() => {
                                onSelectSource(source);
                              }}
                              onMouseEnter={() => {
                                onSelectSource(source);
                              }}
                              type="button"
                            >
                              <CitationBadge tone={toneForStatus(badge.status)}>
                                {badge.label}
                              </CitationBadge>
                            </button>
                          );
                        })}
                      </div>
                    ) : null}

                    <p className="mt-4 text-sm leading-7 text-ink-700">
                      {claim.reason}
                    </p>

                    {claim.appealWarning ? (
                      <p className="mt-3 rounded-[1rem] border border-[rgba(152,80,77,0.18)] bg-[rgba(152,80,77,0.08)] px-3 py-3 text-sm leading-7 text-garnet-500">
                        {claim.appealWarning}
                      </p>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}

            {section.statusItems.length > 0 ? (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {section.statusItems.map((item) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/78 px-4 py-4"
                    key={item.label}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-ink-700">
                      {item.label}
                    </p>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <p className="text-2xl text-ink-950">{item.value}</p>
                      <CitationBadge tone={toneForStatus(item.status)}>
                        {item.status}
                      </CitationBadge>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </SurfaceCard>
  );
}
