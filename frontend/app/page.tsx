import { BootstrapQueryConsole } from "../components/research/BootstrapQueryConsole";

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  return (
    <main className="min-h-screen bg-cream-50 text-text-primary">
      <section className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center gap-8 px-6 py-16">
        <div className="space-y-4">
          <p className="font-mono text-sm uppercase tracking-[0.3em] text-text-secondary">
            NyayaRAG Bootstrap
          </p>
          <h1 className="max-w-4xl font-serif text-5xl leading-tight text-navy-900">
            Trust-first Indian legal research starts with architecture, not
            prompts.
          </h1>
          <p className="max-w-3xl text-lg leading-8 text-text-secondary">
            This workspace is the Phase 0 bootstrap for NyayaRAG. The backend is
            expected at <span className="font-mono">{apiBaseUrl}</span> and the
            product spine is now ready for corpus ingestion and retrieval work.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <article className="rounded-xl border border-gold-400/40 bg-white p-5">
            <h2 className="font-serif text-xl text-navy-900">Frontend</h2>
            <p className="mt-2 text-sm leading-6 text-text-secondary">
              Next.js 14 App Router shell with Tailwind tokens aligned to the
              NyayaRAG legal-library design language.
            </p>
          </article>
          <article className="rounded-xl border border-gold-400/40 bg-white p-5">
            <h2 className="font-serif text-xl text-navy-900">Backend</h2>
            <p className="mt-2 text-sm leading-6 text-text-secondary">
              FastAPI service with a basic health endpoint and Postgres
              connectivity check.
            </p>
          </article>
          <article className="rounded-xl border border-gold-400/40 bg-white p-5">
            <h2 className="font-serif text-xl text-navy-900">Infrastructure</h2>
            <p className="mt-2 text-sm leading-6 text-text-secondary">
              Local Docker Compose setup for PostgreSQL, Qdrant, Neo4j, and
              Redis.
            </p>
          </article>
        </div>

        <BootstrapQueryConsole />
      </section>
    </main>
  );
}
