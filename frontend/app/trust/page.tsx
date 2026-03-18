import Link from "next/link";

import {
  CitationBadge,
  MetricPill,
  SectionLabel,
  SurfaceCard,
} from "../../components/design";
import {
  formatTrustTimestamp,
  getDisplayTrustMetrics,
  getTrustPageData,
} from "../../lib/trust";

export default async function TrustPage() {
  const { apiBaseUrl, snapshot, source } = await getTrustPageData();
  const metrics = getDisplayTrustMetrics(snapshot);

  return (
    <main className="min-h-screen text-ink-900">
      <section className="page-shell flex flex-col gap-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <SectionLabel>Public Trust</SectionLabel>
            <h1 className="text-5xl leading-[0.98] text-ink-950 sm:text-6xl">
              Measured trust has to stay public.
            </h1>
            <p className="max-w-3xl text-sm leading-7 text-ink-700">
              This page renders the benchmark surface behind NyayaRAG&apos;s
              trust claim: benchmark metadata, update timestamp, measured metric
              blocks, and the backend route that published the current snapshot.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Link
              className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-5 py-3 text-sm font-semibold text-ink-950 shadow-card transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
              href="/"
            >
              Back to landing page
            </Link>
            <Link
              className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-5 py-3 text-sm font-semibold text-ink-950 shadow-card transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
              href="/workspace"
            >
              Open workspace
            </Link>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
          <SurfaceCard className="p-6 sm:p-7" tone="ink">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-3">
                <SectionLabel className="text-[rgba(244,236,221,0.72)]">
                  Trust snapshot
                </SectionLabel>
                <h2 className="text-3xl text-paper-50">
                  {snapshot.benchmarkName}
                </h2>
              </div>
              <CitationBadge tone={source === "live" ? "verified" : "uncertain"}>
                {source === "live" ? "Live backend snapshot" : "Preview fallback"}
              </CitationBadge>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <MetricPill
                className="w-full"
                label="Suite"
                tone="ink"
                value={snapshot.suiteName}
              />
              <MetricPill
                className="w-full"
                label="Queries measured"
                tone="brass"
                value={snapshot.queryCount.toLocaleString("en-IN")}
              />
              <MetricPill
                className="w-full"
                label="Benchmark version"
                tone="teal"
                value={snapshot.benchmarkVersion ?? "unversioned"}
              />
              <MetricPill
                className="w-full"
                label="Last updated"
                tone="ink"
                value={formatTrustTimestamp(snapshot.measuredAt)}
              />
            </div>

            <div className="mt-5 rounded-[1.2rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.06)] p-4">
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(244,236,221,0.6)]">
                Backend route
              </p>
              <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.82)]">
                {apiBaseUrl}
                /api/trust
              </p>
              <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.72)]">
                {snapshot.notes ??
                  "This run published benchmark metadata without extra notes."}
              </p>
            </div>
          </SurfaceCard>

          <SurfaceCard className="p-6 sm:p-7" tone="paper">
            <SectionLabel>Measured metrics</SectionLabel>
            <h2 className="mt-3 text-3xl text-ink-950">
              Benchmark rendering stays close to the backend contract.
            </h2>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {metrics.map((metric) => (
                <div
                  className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 p-4"
                  key={metric.key}
                >
                  <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-ink-700">
                    {metric.label}
                  </p>
                  <p className="mt-3 text-3xl text-ink-950">{metric.value}</p>
                </div>
              ))}
            </div>
          </SurfaceCard>
        </div>

        <SurfaceCard className="p-6 sm:p-7" tone="paper">
          <SectionLabel>Benchmark metadata</SectionLabel>
          <h2 className="mt-3 text-3xl text-ink-950">
            The page shows both the run identity and the publishing context.
          </h2>
          <div className="mt-6 grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
            <div className="space-y-3">
              <p className="text-sm leading-7 text-ink-700">
                Run ID: <span className="font-mono text-ink-950">{snapshot.runId}</span>
              </p>
              <p className="text-sm leading-7 text-ink-700">
                Benchmark version:{" "}
                <span className="font-mono text-ink-950">
                  {snapshot.benchmarkVersion ?? "unversioned"}
                </span>
              </p>
              <p className="text-sm leading-7 text-ink-700">
                Publication source:{" "}
                <span className="font-mono text-ink-950">{source}</span>
              </p>
            </div>

            <div className="rounded-[1.2rem] border border-[rgba(16,32,53,0.08)] bg-white/72 p-4">
              <p className="font-mono text-xs uppercase tracking-[0.18em] text-ink-700">
                Payload metadata
              </p>
              {snapshot.payload ? (
                <div className="mt-3 grid gap-2">
                  {Object.entries(snapshot.payload).map(([key, value]) => (
                    <div
                      className="flex items-start justify-between gap-4 rounded-[0.9rem] border border-[rgba(16,32,53,0.08)] bg-paper-50 px-3 py-3"
                      key={key}
                    >
                      <span className="font-mono text-[0.68rem] uppercase tracking-[0.14em] text-ink-700">
                        {key.replaceAll("_", " ")}
                      </span>
                      <span className="max-w-[18rem] text-right text-sm text-ink-950">
                        {String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm leading-7 text-ink-700">
                  No extra payload metadata was published for this run.
                </p>
              )}
            </div>
          </div>
        </SurfaceCard>
      </section>
    </main>
  );
}
