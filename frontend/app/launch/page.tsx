import Link from "next/link";

import {
  CitationBadge,
  MetricPill,
  SectionLabel,
  SurfaceCard,
} from "../../components/design";

const comparisonWorkflow = [
  "Pick one recurring practitioner question with binding authority and one common AI failure mode.",
  "Run the same prompt across NyayaRAG and at least two comparison tools.",
  "Verify every cited authority against the source text before screen capture is published.",
  "Show the exact point where NyayaRAG downgrades uncertainty instead of inventing confidence.",
];

const benchmarkStory = [
  "Lead with the trust number, not with model branding.",
  "Explain the difference between citation fabrication and misgrounding in plain legal language.",
  "Show the measured benchmark route and timestamp before any comparative claim.",
  "Close with the filing-risk argument: lawyers should not need a second tool just to verify the first one.",
];

const distributionChecklist = [
  "Record one comparison demo for Indian legal Twitter and LinkedIn.",
  "Prepare WhatsApp-ready screenshots for chamber and bar-group forwards.",
  "Publish the trust page link beside every demo clip so the benchmark is inspectable.",
  "Keep a live checklist of institutions, chambers, and practitioner groups contacted.",
];

export default function LaunchPage() {
  return (
    <main className="min-h-screen text-ink-900">
      <section className="page-shell flex flex-col gap-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <SectionLabel>Launch Assets</SectionLabel>
            <h1 className="text-5xl leading-[0.98] text-ink-950 sm:text-6xl">
              Launch proof has to be as disciplined as product proof.
            </h1>
            <p className="max-w-3xl text-sm leading-7 text-ink-700">
              This page packages the comparison-demo workflow, the benchmark
              story sequence, and the first distribution checklist into one
              launch surface.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Link
              className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-5 py-3 text-sm font-semibold text-ink-950 shadow-card transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
              href="/trust"
            >
              Open trust page
            </Link>
            <Link
              className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-5 py-3 text-sm font-semibold text-ink-950 shadow-card transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
              href="/workspace"
            >
              Open workspace
            </Link>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[0.92fr_1.08fr]">
          <SurfaceCard className="p-6 sm:p-7" tone="ink">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-3">
                <SectionLabel className="text-[rgba(244,236,221,0.72)]">
                  Comparison demo
                </SectionLabel>
                <h2 className="text-3xl text-paper-50">
                  The demo has to show verification behavior, not just answer quality.
                </h2>
              </div>
              <CitationBadge tone="binding">Public demo</CitationBadge>
            </div>

            <div className="mt-6 grid gap-3">
              {comparisonWorkflow.map((step, index) => (
                <div
                  className="rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.06)] p-4"
                  key={step}
                >
                  <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-[rgba(244,236,221,0.58)]">
                    Step {index + 1}
                  </p>
                  <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.84)]">
                    {step}
                  </p>
                </div>
              ))}
            </div>
          </SurfaceCard>

          <SurfaceCard className="p-6 sm:p-7" tone="paper">
            <SectionLabel>Benchmark storytelling</SectionLabel>
            <h2 className="mt-3 text-3xl text-ink-950">
              The launch narrative should move from risk to measurable proof.
            </h2>
            <div className="mt-6 grid gap-3">
              {benchmarkStory.map((point) => (
                <div
                  className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 p-4"
                  key={point}
                >
                  <p className="text-sm leading-7 text-ink-800">{point}</p>
                </div>
              ))}
            </div>
          </SurfaceCard>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
          <SurfaceCard className="p-6 sm:p-7" tone="paper">
            <SectionLabel>Distribution checklist</SectionLabel>
            <h2 className="mt-3 text-3xl text-ink-950">
              Initial distribution is a checklist, not a vague launch wish.
            </h2>
            <div className="mt-6 grid gap-3">
              {distributionChecklist.map((item) => (
                <div
                  className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 p-4"
                  key={item}
                >
                  <p className="text-sm leading-7 text-ink-800">{item}</p>
                </div>
              ))}
            </div>
          </SurfaceCard>

          <SurfaceCard className="p-6 sm:p-7" tone="muted">
            <SectionLabel>Launch framing</SectionLabel>
            <h2 className="mt-3 text-3xl text-ink-950">
              Keep the message tight enough to survive forwarding.
            </h2>
            <div className="mt-6 grid gap-3">
              <MetricPill
                className="w-full"
                label="Primary claim"
                tone="ink"
                value="Trust architecture, not prompt polish"
              />
              <MetricPill
                className="w-full"
                label="Demo outcome"
                tone="brass"
                value="Show the citation check in public"
              />
              <MetricPill
                className="w-full"
                label="Distribution rule"
                tone="teal"
                value="Every clip links back to measured trust"
              />
            </div>
          </SurfaceCard>
        </div>
      </section>
    </main>
  );
}
