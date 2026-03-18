import Link from "next/link";

import {
  CitationBadge,
  MetricPill,
  SectionLabel,
  SurfaceCard,
} from "../../components/design";
import {
  buildFrontendAuthHeaders,
  resolveFrontendAuthSession,
} from "../../lib/auth-session";
import {
  demoBillingInvoicesForSession,
  demoBillingSummaryForSession,
  pricingTiers,
} from "../../lib/billing";

export default function BillingPage() {
  const authSession = resolveFrontendAuthSession();
  const authHeaders = buildFrontendAuthHeaders(authSession);
  const billingSummary = demoBillingSummaryForSession(authSession);
  const invoices = demoBillingInvoicesForSession(authSession);

  return (
    <main className="min-h-screen text-ink-900">
      <section className="page-shell flex flex-col gap-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <SectionLabel>Billing</SectionLabel>
            <h1 className="text-5xl leading-[0.98] text-ink-950 sm:text-6xl">
              Plan enforcement, checkout flow, and invoice history.
            </h1>
            <p className="max-w-3xl text-sm leading-7 text-ink-700">
              Billing is now part of the trust boundary. Workspace research and
              daily free-tier limits are enforced against the authenticated
              session before the query is accepted.
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
                  Current plan
                </SectionLabel>
                <h2 className="text-3xl text-paper-50">
                  {billingSummary.currentPlanName}
                </h2>
              </div>
              <CitationBadge tone="binding">
                {authSession.isAuthenticated ? "Authenticated" : "Anonymous"}
              </CitationBadge>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <MetricPill
                className="w-full"
                label="Plan price"
                tone="ink"
                value={`${billingSummary.price}${billingSummary.cadence}`}
              />
              <MetricPill
                className="w-full"
                label="Workspace access"
                tone={billingSummary.workspaceAccess ? "teal" : "brass"}
                value={billingSummary.workspaceAccess ? "Enabled" : "Upgrade required"}
              />
              <MetricPill
                className="w-full"
                label="Daily limit"
                tone="brass"
                value={
                  billingSummary.dailyQueryLimit !== null
                    ? `${billingSummary.dailyQueryLimit} queries`
                    : "Unlimited"
                }
              />
              <MetricPill
                className="w-full"
                label="Auth bridge"
                tone="ink"
                value={Object.keys(authHeaders).length > 0 ? "Headers ready" : "No auth headers"}
              />
            </div>

            <div className="mt-5 rounded-[1.2rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.06)] p-4">
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(244,236,221,0.6)]">
                Razorpay hook
              </p>
              <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.82)]">
                Checkout sessions are now generated through the backend billing
                route, and paid plans unlock workspace-scoped research.
              </p>
            </div>
          </SurfaceCard>

          <SurfaceCard className="p-6 sm:p-7" tone="paper">
            <SectionLabel>Plan catalog</SectionLabel>
            <h2 className="mt-3 text-3xl text-ink-950">
              Razorpay-backed plans mapped to product entitlements.
            </h2>
            <div className="mt-6 grid gap-4 lg:grid-cols-3">
              {pricingTiers.map((tier) => (
                <div
                  className="rounded-[1.2rem] border border-[rgba(16,32,53,0.08)] bg-white/72 p-4"
                  key={tier.code}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-ink-700">
                        {tier.name}
                      </p>
                      <p className="mt-3 text-3xl text-ink-950">{tier.price}</p>
                      <p className="text-sm text-ink-700">{tier.cadence}</p>
                    </div>
                    {tier.badge ? (
                      <CitationBadge tone="verified">{tier.badge}</CitationBadge>
                    ) : null}
                  </div>
                  <ul className="mt-4 space-y-2 text-sm leading-7 text-ink-800">
                    {tier.points.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </SurfaceCard>
        </div>

        <SurfaceCard className="p-6 sm:p-7" tone="paper">
          <SectionLabel>Invoice history</SectionLabel>
          <h2 className="mt-3 text-3xl text-ink-950">
            Billing history stays visible beside plan enforcement.
          </h2>
          <div className="mt-6 grid gap-3">
            {invoices.length === 0 ? (
              <p className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 px-4 py-4 text-sm leading-7 text-ink-700">
                No invoices yet. Sign in and start a paid plan to populate the
                Razorpay invoice history hook.
              </p>
            ) : (
              invoices.map((invoice) => (
                <div
                  className="flex flex-col gap-3 rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 px-4 py-4 sm:flex-row sm:items-center sm:justify-between"
                  key={`${invoice.issuedAt}-${invoice.description}`}
                >
                  <div>
                    <p className="text-sm font-semibold text-ink-950">
                      {invoice.description}
                    </p>
                    <p className="mt-1 text-xs uppercase tracking-[0.16em] text-ink-700">
                      {invoice.issuedAt}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <CitationBadge
                      tone={
                        invoice.status === "paid"
                          ? "verified"
                          : invoice.status === "issued"
                            ? "uncertain"
                            : "unverified"
                      }
                    >
                      {invoice.status}
                    </CitationBadge>
                    <span className="text-sm font-semibold text-ink-950">
                      {invoice.amount}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </SurfaceCard>
      </section>
    </main>
  );
}
