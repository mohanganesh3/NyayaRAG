import Link from "next/link";

import { SectionLabel } from "../../components/design";
import { WorkspaceShell } from "../../components/workspace/WorkspaceShell";
import {
  buildFrontendAuthHeaders,
  resolveFrontendAuthSession,
} from "../../lib/auth-session";
import { demoQueryHistoryForSession } from "../../lib/query-history";
import { demoWorkspaceContext } from "../../lib/workspace";

export default function WorkspacePage() {
  const authSession = resolveFrontendAuthSession();
  const authHeaders = buildFrontendAuthHeaders(authSession);
  const queryHistory = demoQueryHistoryForSession(
    authSession,
    demoWorkspaceContext.case_id,
  );

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
          </div>

          <Link
            className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-5 py-3 text-sm font-semibold text-ink-950 shadow-card transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
            href="/"
          >
            Back to landing page
          </Link>
        </div>

        <WorkspaceShell
          authHeaders={authHeaders}
          authSession={authSession}
          context={demoWorkspaceContext}
          queryHistory={queryHistory}
        />
      </section>
    </main>
  );
}
