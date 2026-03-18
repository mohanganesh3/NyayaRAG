import Link from "next/link";

import { BootstrapQueryConsole } from "../components/research/BootstrapQueryConsole";
import {
  CitationBadge,
  MetricPill,
  SectionLabel,
  SurfaceCard,
} from "../components/design";
import { pricingTiers } from "../lib/billing";

const proofLayers = [
  {
    title: "Placeholder-only generation",
    detail: "The model never writes raw citations directly into verified output.",
  },
  {
    title: "Misgrounding detection",
    detail: "A real citation still fails if the passage does not support the claim.",
  },
  {
    title: "Appeal-chain validation",
    detail: "Intermediate reversed judgments are redirected to final authority.",
  },
  {
    title: "Temporal statute checks",
    detail: "Repealed and amended provisions are caught before they reach the answer.",
  },
];

const dashboardPreview = [
  { label: "Citation existence gate", value: "Required: 100%" },
  { label: "Citation accuracy target", value: ">98%" },
  { label: "Appeal-chain accuracy", value: "Required: 100%" },
  { label: "Temporal validity", value: "Required: 100%" },
];

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  return (
    <main className="min-h-screen text-ink-900">
      <section className="page-shell flex flex-col gap-10">
        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr] xl:items-start">
          <div className="space-y-6">
            <SectionLabel>NyayaRAG</SectionLabel>
            <h1 className="max-w-4xl text-5xl leading-[0.98] text-ink-950 sm:text-6xl">
              Trust-first Indian legal research starts with architecture, not
              prompts.
            </h1>
            <p className="max-w-3xl text-lg leading-8 text-ink-700">
              NyayaRAG is built for Indian advocates who need one system they
              can trust before they draft, cite, or file. The landing page has
              to prove that in one screenful: routed retrieval, mandatory
              verification, public benchmarks, and pricing that undercuts the
              tools lawyers currently pair with AI anyway. The backend is
              expected at{" "}
              <span className="font-mono text-sm text-ink-950">{apiBaseUrl}</span>.
            </p>

            <div className="flex flex-wrap gap-3">
              <MetricPill
                label="Pipelines"
                tone="ink"
                value="5 routed research paths"
              />
              <MetricPill
                label="Verification"
                tone="brass"
                value="5 mandatory answer gates"
              />
              <MetricPill
                label="Advocate Pro"
                tone="teal"
                value="₹799 / month"
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2" id="proof">
              {proofLayers.map((layer) => (
                <SurfaceCard className="p-4" key={layer.title} tone="paper">
                  <p className="font-mono text-xs uppercase tracking-[0.22em] text-ink-700">
                    {layer.title}
                  </p>
                  <p className="mt-3 text-sm leading-7 text-ink-800">
                    {layer.detail}
                  </p>
                </SurfaceCard>
              ))}
            </div>
          </div>

          <SurfaceCard className="p-6 sm:p-7" tone="ink">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-2">
                <SectionLabel className="text-[rgba(244,236,221,0.72)]">
                  Trust Number
                </SectionLabel>
                <h2 className="text-3xl text-paper-50">
                  Verified output has zero room for invented authority.
                </h2>
              </div>
              <CitationBadge tone="binding">Binding</CitationBadge>
            </div>

            <div className="mt-6 grid gap-4">
              <div className="rounded-[1.4rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.08)] px-5 py-6">
                <p className="font-mono text-xs uppercase tracking-[0.24em] text-[rgba(244,236,221,0.58)]">
                  Citation Fabrication Allowance
                </p>
                <div className="mt-3 flex items-end gap-3">
                  <span className="font-serif text-7xl leading-none text-paper-50">
                    0
                  </span>
                  <div className="pb-2">
                    <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(244,236,221,0.58)]">
                      fabricated citations can enter verified output
                    </p>
                    <p className="mt-2 max-w-sm text-sm leading-7 text-[rgba(252,247,239,0.78)]">
                      Public weekly metrics will appear after measured
                      evaluation runs go live. Until then, the claim shown here
                      is the architectural rule, not a marketing statistic.
                    </p>
                  </div>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {dashboardPreview.map((metric) => (
                  <div
                    className="rounded-[1.1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.06)] p-4"
                    key={metric.label}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.22em] text-[rgba(244,236,221,0.54)]">
                      {metric.label}
                    </p>
                    <p className="mt-3 text-xl text-paper-50">{metric.value}</p>
                  </div>
                ))}
              </div>

              <div className="source-callout bg-[rgba(252,247,239,0.95)] text-ink-900">
                <p className="font-mono text-xs uppercase tracking-[0.22em] text-ink-700">
                  Proof-Oriented Positioning
                </p>
                <p className="mt-3 text-sm leading-7 text-ink-800">
                  Every existing competitor still asks lawyers to verify
                  citations elsewhere before filing. NyayaRAG is positioned as
                  the first system that treats trust architecture as the product
                  itself.
                </p>
              </div>
            </div>
          </SurfaceCard>
        </div>

        <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
          <SurfaceCard className="p-6 sm:p-7" tone="paper">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <SectionLabel>Trust Dashboard Preview</SectionLabel>
                <h2 className="mt-3 text-3xl text-ink-950">
                  The homepage sells proof, not adjectives.
                </h2>
              </div>
              <CitationBadge tone="verified">Public metrics</CitationBadge>
            </div>

            <div className="mt-6 grid gap-4 lg:grid-cols-[0.92fr_1.08fr]">
              <div className="space-y-4">
                <p className="text-sm leading-7 text-ink-700">
                  The measured dashboard route already exists in the backend.
                  The landing page should preview the benchmark story without
                  faking numbers that are not yet measured.
                </p>
                <div className="flex flex-wrap gap-2">
                  <CitationBadge tone="verified">Citation existence</CitationBadge>
                  <CitationBadge tone="uncertain">Weekly benchmark</CitationBadge>
                  <CitationBadge tone="persuasive">Public /api/trust</CitationBadge>
                </div>
              </div>

              <div className="rounded-[1.35rem] border border-[rgba(16,32,53,0.08)] bg-white/70 p-4">
                <div className="grid gap-3">
                  {dashboardPreview.map((metric) => (
                    <div
                      className="flex items-center justify-between rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50 px-4 py-3"
                      key={metric.label}
                    >
                      <span className="font-mono text-[0.7rem] uppercase tracking-[0.18em] text-ink-700">
                        {metric.label}
                      </span>
                      <span className="text-sm font-semibold text-ink-950">
                        {metric.value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </SurfaceCard>

          <SurfaceCard className="p-6 sm:p-7" tone="muted">
            <SectionLabel>Positioning</SectionLabel>
            <h2 className="mt-3 text-3xl text-ink-950">
              One number on the homepage. One reason to trust it.
            </h2>
            <p className="mt-4 text-sm leading-7 text-ink-700">
              Lawyers currently lock citations in one product and ask questions
              in another. NyayaRAG only wins if the homepage makes that broken
              workflow feel obsolete.
            </p>
            <div className="mt-6 grid gap-3">
              <MetricPill
                className="w-full"
                label="Market gap"
                tone="brass"
                value="Trust is still outsourced"
              />
              <MetricPill
                className="w-full"
                label="NyayaRAG claim"
                tone="ink"
                value="Verification architecture is the product"
              />
              <MetricPill
                className="w-full"
                label="Go-to-market"
                tone="teal"
                value="Homepage proof -> workspace proof -> filing trust"
              />
            </div>
          </SurfaceCard>
        </div>

        <div className="space-y-5" id="pricing">
          <div className="space-y-3">
            <SectionLabel>Pricing</SectionLabel>
            <h2 className="text-4xl text-ink-950">
              Lower than legacy research, without weakening verification.
            </h2>
            <p className="max-w-3xl text-sm leading-7 text-ink-700">
              Pricing stays tied to the brief: affordable for junior advocates,
              sustainable for chambers, and identical trust rules across every
              plan.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link
                className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-5 py-3 text-sm font-semibold text-ink-950 shadow-card transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
                href="/billing"
              >
                Manage plans and billing
              </Link>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            {pricingTiers.map((tier) => (
              <SurfaceCard className="p-5" key={tier.name} tone={tier.tone}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <SectionLabel
                      className={tier.tone === "ink" ? "text-[rgba(244,236,221,0.72)]" : undefined}
                    >
                      {tier.name}
                    </SectionLabel>
                    <div
                      className={`mt-4 flex items-end gap-2 ${tier.tone === "ink" ? "text-paper-50" : "text-ink-950"}`}
                    >
                      <span className="font-serif text-5xl leading-none">
                        {tier.price}
                      </span>
                      <span className="pb-1 text-sm font-medium opacity-70">
                        {tier.cadence}
                      </span>
                    </div>
                  </div>
                  {tier.badge ? (
                    <CitationBadge tone="verified">{tier.badge}</CitationBadge>
                  ) : null}
                </div>

                <ul
                  className={`mt-5 space-y-3 text-sm leading-7 ${tier.tone === "ink" ? "text-[rgba(252,247,239,0.82)]" : "text-ink-700"}`}
                >
                  {tier.points.map((point) => (
                    <li className="border-b border-current/10 pb-3" key={point}>
                      {point}
                    </li>
                  ))}
                </ul>
              </SurfaceCard>
            ))}
          </div>
        </div>

        <BootstrapQueryConsole />
      </section>
    </main>
  );
}
