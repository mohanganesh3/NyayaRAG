import Link from "next/link";

import { SectionLabel } from "../../components/design";
import { WorkspaceShell } from "../../components/workspace/WorkspaceShell";
import {
  buildFrontendAuthHeaders,
  resolveFrontendAuthSession,
} from "../../lib/auth-session";
import { getWorkspacePageData } from "../../lib/workspace-page";

type WorkspacePageProps = {
  searchParams?:
    | Promise<Record<string, string | string[] | undefined>>
    | Record<string, string | string[] | undefined>;
};

async function resolveSearchParams(
  searchParams: WorkspacePageProps["searchParams"],
): Promise<Record<string, string | string[] | undefined>> {
  if (!searchParams) {
    return {};
  }
  if (typeof (searchParams as Promise<unknown>).then === "function") {
    return (await searchParams) as Record<string, string | string[] | undefined>;
  }
  return searchParams;
}

export default async function WorkspacePage({ searchParams }: WorkspacePageProps = {}) {
  const authSession = resolveFrontendAuthSession();
  const authHeaders = buildFrontendAuthHeaders(authSession);
  const resolvedSearchParams = await resolveSearchParams(searchParams);
  const { availableWorkspaces, context, queryHistory, savedAnswers, source } =
    await getWorkspacePageData({
      authHeaders,
      authSession,
      requestedCaseId: resolvedSearchParams.case,
    });

  return (
    <main className="min-h-screen text-ink-900">
      <section className="page-shell flex flex-col gap-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <SectionLabel>Workspace</SectionLabel>
            <h1 className="text-5xl leading-[0.98] text-ink-950 sm:text-6xl">
              Three panels, one legal research flow.
            </h1>
            <p className="max-w-3xl text-sm leading-7 text-ink-700">
              This route is the protected product shell: case context on the
              left, research flow in the center, source evidence on the right.
            </p>
            <p className="text-xs uppercase tracking-[0.18em] text-ink-700">
              {source === "live"
                ? "Live backend workspace"
                : "Preview workspace fallback"}
            </p>
          </div>

          <Link
            className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-5 py-3 text-sm font-semibold text-ink-950 shadow-card transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
            href="/"
          >
            Back to landing page
          </Link>
          <Link
            className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-5 py-3 text-sm font-semibold text-ink-950 shadow-card transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
            href="/billing"
          >
            Manage billing
          </Link>
        </div>

        <WorkspaceShell
          availableWorkspaces={availableWorkspaces}
          authHeaders={authHeaders}
          authSession={authSession}
          context={context}
          savedAnswers={savedAnswers}
          queryHistory={queryHistory}
        />
      </section>
    </main>
  );
}
