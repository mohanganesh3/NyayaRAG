import { BootstrapQueryConsole } from "../components/research/BootstrapQueryConsole";
import {
  CitationBadge,
  MetricPill,
  SectionLabel,
  SurfaceCard,
} from "../components/design";

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  return (
    <main className="min-h-screen text-ink-900">
      <section className="page-shell flex min-h-screen flex-col justify-center gap-10">
        <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr] xl:items-start">
          <div className="space-y-6">
            <SectionLabel>NyayaRAG Design System</SectionLabel>
            <h1 className="max-w-4xl text-5xl leading-[0.98] text-ink-950 sm:text-6xl">
              Trust-first Indian legal research starts with architecture, not
              prompts.
            </h1>
            <p className="max-w-3xl text-lg leading-8 text-ink-700">
              This workspace is the first visual system for NyayaRAG: vellum
              surfaces, authority-weighted badges, and a process display that
              shows verification work instead of hiding behind a spinner. The
              backend is expected at{" "}
              <span className="font-mono text-sm text-ink-950">{apiBaseUrl}</span>.
            </p>

            <div className="flex flex-wrap gap-3">
              <MetricPill
                label="Primary shell"
                tone="ink"
                value="Ink + vellum surfaces"
              />
              <MetricPill
                label="Citation states"
                tone="brass"
                value="Verified, uncertain, unverified"
              />
              <MetricPill
                label="Process mode"
                tone="teal"
                value="Monospace verification timeline"
              />
            </div>
          </div>

          <SurfaceCard className="p-6 sm:p-7" tone="ink">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-2">
                <SectionLabel className="text-[rgba(244,236,221,0.72)]">
                  Authority Preview
                </SectionLabel>
                <h2 className="text-3xl text-paper-50">
                  Legal-library styling, not generic startup chrome.
                </h2>
              </div>
              <CitationBadge tone="binding">Binding</CitationBadge>
            </div>

            <div className="mt-6 space-y-4">
              <div className="rounded-[1.15rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.08)] p-4">
                <p className="font-mono text-xs uppercase tracking-[0.24em] text-[rgba(244,236,221,0.58)]">
                  Citation States
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <CitationBadge tone="verified">Verified</CitationBadge>
                  <CitationBadge tone="uncertain">Uncertain</CitationBadge>
                  <CitationBadge tone="unverified">Unverified</CitationBadge>
                  <CitationBadge tone="persuasive">Persuasive</CitationBadge>
                </div>
              </div>

              <div className="source-callout bg-[rgba(252,247,239,0.95)] text-ink-900">
                <p className="font-mono text-xs uppercase tracking-[0.22em] text-ink-700">
                  Source Viewer Behavior
                </p>
                <p className="mt-3 text-sm leading-7 text-ink-800">
                  Hovered citations open exact passages. Reversed authorities
                  surface with warning banners. Unverified propositions stay
                  visible, but they never masquerade as checked law.
                </p>
              </div>
            </div>
          </SurfaceCard>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <SurfaceCard className="p-5" tone="paper">
            <SectionLabel>Frontend</SectionLabel>
            <h2 className="mt-3 text-2xl text-ink-950">Workspace shell</h2>
            <p className="mt-3 text-sm leading-7 text-ink-700">
              Next.js 14 App Router with a legal-library palette, strong type
              hierarchy, and reusable trust primitives instead of one-off
              screens.
            </p>
          </SurfaceCard>
          <SurfaceCard className="p-5" tone="paper">
            <SectionLabel>Backend</SectionLabel>
            <h2 className="mt-3 text-2xl text-ink-950">Verification spine</h2>
            <p className="mt-3 text-sm leading-7 text-ink-700">
              FastAPI now exposes routed retrieval, citation resolution,
              misgrounding checks, appeal validation, and evaluation services.
            </p>
          </SurfaceCard>
          <SurfaceCard className="p-5" tone="muted">
            <SectionLabel>Infrastructure</SectionLabel>
            <h2 className="mt-3 text-2xl text-ink-950">Corpus-ready runtime</h2>
            <p className="mt-3 text-sm leading-7 text-ink-700">
              PostgreSQL, Qdrant, Neo4j, and Redis stay behind a local compose
              setup so this visual system can scale straight into real corpus
              ingestion.
            </p>
          </SurfaceCard>
        </div>

        <BootstrapQueryConsole />
      </section>
    </main>
  );
}
