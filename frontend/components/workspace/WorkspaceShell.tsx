"use client";

import { useEffect, useState } from "react";

import { BootstrapQueryConsole } from "../research/BootstrapQueryConsole";
import { createInitialQueryStreamState } from "../../lib/query-stream";
import type { FrontendAuthSession } from "../../lib/auth-session";
import type { WorkspaceQueryHistoryPreview } from "../../lib/query-history";
import {
  CitationBadge,
  MetricPill,
  SectionLabel,
  SurfaceCard,
} from "../design";
import {
  collectStructuredAnswerSources,
  demoStructuredAnswer,
  serializeStructuredAnswerToMarkdown,
  type StructuredAnswer,
  type StructuredAnswerSource,
} from "../../lib/structured-answer";
import {
  fetchCitationSource,
  fetchWorkspaceHistory,
  uploadWorkspaceDocuments,
  type WorkspaceCitationSource,
} from "../../lib/workspace-api";
import {
  workspaceContextStorageKey,
  workspaceHistoryStorageKey,
  workspaceSavedAnswersStorageKey,
  type WorkspaceCaseContext,
} from "../../lib/workspace";
import { CitationGraph } from "./CitationGraph";
import { StructuredAnswerRenderer } from "./StructuredAnswerRenderer";
import { TransparencyDrawer } from "./TransparencyDrawer";

type WorkspaceShellProps = {
  authHeaders: Record<string, string>;
  authSession: FrontendAuthSession;
  context: WorkspaceCaseContext;
  queryHistory: WorkspaceQueryHistoryPreview[];
};

const suggestedQueries = [
  "What are the strongest anticipatory bail arguments on these facts?",
  "Which Supreme Court authorities support treating this as a civil dispute?",
  "What weaknesses will the prosecution press in reply?",
];

type SavedWorkspaceAnswer = {
  answer: StructuredAnswer;
  id: string;
  query: string;
  savedAt: string;
};

type UploadStatus =
  | "idle"
  | "selected"
  | "uploading"
  | "processing"
  | "ready"
  | "error";

function toTitleCase(value: string | null): string {
  if (!value) {
    return "Not set";
  }

  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatHistoryTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("en-IN", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function downloadTextFile(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(href);
}

function resolveBrowserStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }

  const storageCandidate = window.localStorage;
  if (
    typeof storageCandidate?.getItem !== "function" ||
    typeof storageCandidate?.setItem !== "function" ||
    typeof storageCandidate?.removeItem !== "function"
  ) {
    return null;
  }

  return storageCandidate;
}

export function WorkspaceShell({
  authHeaders,
  authSession,
  context: initialContext,
  queryHistory: initialQueryHistory,
}: WorkspaceShellProps) {
  const defaultWorkspaceQuery =
    "What are the strongest anticipatory bail arguments on these facts, and which binding Supreme Court cases should appear first in the note?";
  const [streamState, setStreamState] = useState(createInitialQueryStreamState);
  const [isTransparencyOpen, setIsTransparencyOpen] = useState(false);
  const [workspaceContext, setWorkspaceContext] =
    useState<WorkspaceCaseContext>(initialContext);
  const [workspaceHistory, setWorkspaceHistory] =
    useState<WorkspaceQueryHistoryPreview[]>(initialQueryHistory);
  const [savedAnswers, setSavedAnswers] = useState<SavedWorkspaceAnswer[]>([]);
  const [selectedSavedAnswerId, setSelectedSavedAnswerId] = useState<string | null>(null);
  const [sourceViewerCache, setSourceViewerCache] = useState<
    Record<string, WorkspaceCitationSource>
  >({});
  const [sourceViewerError, setSourceViewerError] = useState<string | null>(null);
  const [sourceViewerLoadingId, setSourceViewerLoadingId] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [lastSubmittedQuery, setLastSubmittedQuery] = useState<string | null>(null);
  const activeSavedAnswer =
    savedAnswers.find((entry) => entry.id === selectedSavedAnswerId) ?? null;
  const activeAnswer: StructuredAnswer =
    streamState.structuredAnswer ?? activeSavedAnswer?.answer ?? demoStructuredAnswer;
  const availableSources = collectStructuredAnswerSources(activeAnswer);
  const [activeSourceId, setActiveSourceId] = useState<string | null>(
    availableSources[0]?.id ?? null,
  );
  const storageScopeKey = workspaceContextStorageKey(authSession.userId);
  const historyStorageKey = workspaceHistoryStorageKey(workspaceContext.case_id);
  const savedAnswersStorageKey = workspaceSavedAnswersStorageKey(
    workspaceContext.case_id,
  );

  useEffect(() => {
    const storage = resolveBrowserStorage();
    if (!storage) {
      return;
    }

    const persistedContext = storage.getItem(storageScopeKey);
    if (persistedContext) {
      try {
        setWorkspaceContext(JSON.parse(persistedContext) as WorkspaceCaseContext);
      } catch {
        storage.removeItem(storageScopeKey);
      }
    }
  }, [storageScopeKey]);

  useEffect(() => {
    const storage = resolveBrowserStorage();
    if (!storage) {
      return;
    }

    storage.setItem(storageScopeKey, JSON.stringify(workspaceContext));
  }, [storageScopeKey, workspaceContext]);

  useEffect(() => {
    const storage = resolveBrowserStorage();
    if (!storage) {
      return;
    }

    const persistedHistory = storage.getItem(historyStorageKey);
    if (persistedHistory) {
      try {
        setWorkspaceHistory(
          JSON.parse(persistedHistory) as WorkspaceQueryHistoryPreview[],
        );
        return;
      } catch {
        storage.removeItem(historyStorageKey);
      }
    }

    setWorkspaceHistory(initialQueryHistory);
  }, [historyStorageKey, initialQueryHistory]);

  useEffect(() => {
    const storage = resolveBrowserStorage();
    if (!storage) {
      return;
    }

    storage.setItem(historyStorageKey, JSON.stringify(workspaceHistory));
  }, [historyStorageKey, workspaceHistory]);

  useEffect(() => {
    const storage = resolveBrowserStorage();
    if (!storage) {
      return;
    }

    const persistedAnswers = storage.getItem(savedAnswersStorageKey);
    if (persistedAnswers) {
      try {
        setSavedAnswers(JSON.parse(persistedAnswers) as SavedWorkspaceAnswer[]);
        return;
      } catch {
        storage.removeItem(savedAnswersStorageKey);
      }
    }

    setSavedAnswers([]);
  }, [savedAnswersStorageKey]);

  useEffect(() => {
    const storage = resolveBrowserStorage();
    if (!storage) {
      return;
    }

    storage.setItem(savedAnswersStorageKey, JSON.stringify(savedAnswers));
  }, [savedAnswers, savedAnswersStorageKey]);

  useEffect(() => {
    if (!lastSubmittedQuery) {
      return;
    }
    if (streamState.status !== "complete" && streamState.status !== "error") {
      return;
    }

    setWorkspaceHistory((currentHistory) => [
      {
        createdAt: new Date().toISOString(),
        pipeline:
          workspaceContext.uploaded_docs.length > 0 ? "agentic_rag" : "hybrid_rag",
        query: lastSubmittedQuery,
        status: streamState.status === "complete" ? "completed" : "error",
        workspaceId: workspaceContext.case_id,
      },
      ...currentHistory.filter((entry) => entry.query !== lastSubmittedQuery),
    ]);
    setLastSubmittedQuery(null);
  }, [
    lastSubmittedQuery,
    streamState.status,
    workspaceContext.case_id,
    workspaceContext.uploaded_docs.length,
  ]);

  useEffect(() => {
    if (!authSession.isAuthenticated || workspaceContext.case_id === initialContext.case_id) {
      return;
    }

    let cancelled = false;
    void fetchWorkspaceHistory({
      authHeaders,
      caseId: workspaceContext.case_id,
    })
      .then((history) => {
        if (!cancelled && history.length > 0) {
          setWorkspaceHistory(history);
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [
    authHeaders,
    authSession.isAuthenticated,
    initialContext.case_id,
    workspaceContext.case_id,
  ]);

  useEffect(() => {
    if (availableSources.length === 0) {
      if (activeSourceId !== null) {
        setActiveSourceId(null);
      }
      return;
    }

    const sourceStillAvailable = availableSources.some(
      (source) => source.id === activeSourceId,
    );
    if (!sourceStillAvailable) {
      setActiveSourceId(availableSources[0]?.id ?? null);
    }
  }, [activeSourceId, availableSources]);

  const activeSource =
    availableSources.find((source) => source.id === activeSourceId) ??
    availableSources[0] ??
    null;
  const activeFetchedSource =
    activeSource !== null ? sourceViewerCache[activeSource.id] ?? null : null;
  const relatedSources = availableSources.filter(
    (source) => source.id !== activeSource?.id,
  );
  const transparencyEventCount =
    streamState.steps.length +
    streamState.agentLogs.length +
    streamState.citationResolutions.length;
  const uploadStatusLabel =
    uploadStatus === "selected"
      ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} selected`
      : uploadStatus === "uploading"
        ? "Uploading bundle"
        : uploadStatus === "processing"
          ? "Running OCR and context extraction"
          : uploadStatus === "ready"
            ? "Workspace persisted"
            : uploadStatus === "error"
              ? "Upload error"
              : "Awaiting files";

  function handleSelectSource(source: StructuredAnswerSource) {
    setActiveSourceId(source.id);
    setSourceViewerError(null);
    if (!source.docId || sourceViewerCache[source.id] || sourceViewerLoadingId === source.id) {
      return;
    }

    setSourceViewerLoadingId(source.id);
    void fetchCitationSource({
      authHeaders,
      chunkId: source.chunkId,
      docId: source.docId,
    })
      .then((resolvedSource) => {
        setSourceViewerCache((currentCache) => ({
          ...currentCache,
          [source.id]: resolvedSource,
        }));
      })
      .catch((error) => {
        setSourceViewerError(
          error instanceof Error ? error.message : "Source lookup failed.",
        );
      })
      .finally(() => {
        setSourceViewerLoadingId((currentLoadingId) =>
          currentLoadingId === source.id ? null : currentLoadingId,
        );
      });
  }

  function handleSelectFiles(fileList: FileList | null) {
    const files = fileList ? Array.from(fileList) : [];
    setSelectedFiles(files);
    setUploadError(null);
    setUploadStatus(files.length > 0 ? "selected" : "idle");
  }

  async function handleUploadDocuments() {
    if (selectedFiles.length === 0) {
      return;
    }

    setUploadError(null);
    setUploadStatus("uploading");

    try {
      setUploadStatus("processing");
      const uploadedContext = await uploadWorkspaceDocuments({
        authHeaders,
        caseId: workspaceContext.case_id,
        caseNumber: workspaceContext.case_number,
        court: workspaceContext.court,
        files: selectedFiles,
      });
      setWorkspaceContext(uploadedContext);
      setSelectedFiles([]);
      setUploadStatus("ready");
    } catch (error) {
      setUploadStatus("error");
      setUploadError(
        error instanceof Error ? error.message : "Workspace upload failed.",
      );
    }
  }

  function handleSaveAnswer() {
    const answerToSave = streamState.structuredAnswer ?? activeAnswer;
    const query = answerToSave.query || "Saved answer";
    const savedAt = new Date().toISOString();
    const entry: SavedWorkspaceAnswer = {
      answer: answerToSave,
      id: `${workspaceContext.case_id}-${savedAt}`,
      query,
      savedAt,
    };
    setSavedAnswers((currentAnswers) => [entry, ...currentAnswers].slice(0, 8));
    setSelectedSavedAnswerId(entry.id);
  }

  function handleExportAnswer() {
    const filename = `${workspaceContext.case_id}-answer.md`;
    downloadTextFile(filename, serializeStructuredAnswerToMarkdown(activeAnswer));
  }

  const activeSourceCitation =
    activeFetchedSource?.effectiveCitation ??
    activeSource?.citation ??
    "No source selected yet.";
  const activeSourceDocId = activeFetchedSource?.effectiveDocId ?? activeSource?.docId ?? null;
  const activeSourcePassage =
    activeFetchedSource?.sourcePassage ?? activeSource?.sourcePassage ?? null;
  const activeSourceMessage = activeFetchedSource
    ? [
        activeFetchedSource.title,
        activeFetchedSource.sourceSystem,
        activeFetchedSource.sourceDocumentRef,
      ]
        .filter((part): part is string => Boolean(part))
        .join(" · ")
    : activeSource?.message ?? null;
  const activeAppealWarning =
    activeFetchedSource?.appealWarning ?? activeSource?.appealWarning ?? null;

  return (
    <div className="grid gap-4 xl:grid-cols-[19rem_minmax(0,1fr)_20rem] xl:items-start">
      <div className="space-y-4 xl:sticky xl:top-6">
        <SurfaceCard className="p-5" tone="paper">
          <SectionLabel>Case context</SectionLabel>
          <h1 className="mt-3 text-3xl text-ink-950">
            {workspaceContext.appellant_petitioner} v.{" "}
            {workspaceContext.respondent_opposite_party}
          </h1>
          <p className="mt-3 text-sm leading-7 text-ink-700">
            {workspaceContext.case_number} · {workspaceContext.court}
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            <CitationBadge tone="binding">Protected workspace</CitationBadge>
            <CitationBadge
              tone={authSession.isAuthenticated ? "verified" : "unverified"}
            >
              {authSession.isAuthenticated ? "Authenticated" : "Sign-in required"}
            </CitationBadge>
          </div>

          <div className="mt-5 grid gap-3">
            <MetricPill
              className="w-full"
              label="Case type"
              tone="ink"
              value={toTitleCase(workspaceContext.case_type)}
            />
            <MetricPill
              className="w-full"
              label="Current stage"
              tone="brass"
              value={toTitleCase(workspaceContext.stage)}
            />
            <MetricPill
              className="w-full"
              label="Extraction confidence"
              tone="teal"
              value={`${Math.round(workspaceContext.doc_extraction_confidence * 100)}%`}
            />
            <MetricPill
              className="w-full"
              label="Session"
              tone="ink"
              value={authSession.userId ?? "Not signed in"}
            />
          </div>

          <div className="mt-6 space-y-5">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.22em] text-ink-700">
                Advocates
              </p>
              <ul className="mt-3 space-y-2 text-sm leading-7 text-ink-800">
                {workspaceContext.advocates.map((advocate) => (
                  <li
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/70 px-3 py-2"
                    key={advocate}
                  >
                    {advocate}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="font-mono text-xs uppercase tracking-[0.22em] text-ink-700">
                Uploaded documents
              </p>
              <div className="mt-3 space-y-3">
                {workspaceContext.uploaded_docs.map((document) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 px-3 py-3"
                    key={document.name}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-ink-950">
                          {document.name}
                        </p>
                        <p className="mt-1 text-xs uppercase tracking-[0.18em] text-ink-700">
                          {document.document_type} · {document.pages} pages
                        </p>
                      </div>
                      <CitationBadge tone="verified">
                        {Math.round(document.confidence * 100)}%
                      </CitationBadge>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-6 rounded-[1rem] border border-dashed border-[rgba(16,32,53,0.12)] bg-white/72 p-4">
            <p className="font-mono text-xs uppercase tracking-[0.22em] text-ink-700">
              Upload workspace files
            </p>
            <p className="mt-3 text-sm leading-7 text-ink-800">
              Drop FIRs, charge sheets, orders, or draft notes into the active
              workspace. The backend will OCR, normalize, and rebuild the case
              context under the same protected case id.
            </p>
            <label
              className="mt-4 flex cursor-pointer flex-col items-center justify-center rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/75 px-4 py-5 text-center text-sm leading-7 text-ink-800 transition hover:border-[rgba(171,127,40,0.28)]"
              htmlFor="workspace-upload-input"
            >
              <span className="font-semibold text-ink-950">
                Select documents for OCR and context rebuild
              </span>
              <span className="mt-1 text-xs uppercase tracking-[0.18em] text-ink-700">
                PDF, image, or DOCX
              </span>
            </label>
            <input
              className="sr-only"
              id="workspace-upload-input"
              multiple
              onChange={(event) => {
                handleSelectFiles(event.target.files);
              }}
              type="file"
            />

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <MetricPill label="OCR progress" tone="teal" value={uploadStatusLabel} />
              {uploadError ? (
                <CitationBadge tone="unverified">{uploadError}</CitationBadge>
              ) : null}
            </div>

            {selectedFiles.length > 0 ? (
              <ul className="mt-4 space-y-2 text-sm leading-7 text-ink-800">
                {selectedFiles.map((file) => (
                  <li
                    className="rounded-[0.95rem] border border-[rgba(16,32,53,0.08)] bg-white/76 px-3 py-2"
                    key={`${file.name}-${file.size}`}
                  >
                    {file.name}
                  </li>
                ))}
              </ul>
            ) : null}

            <button
              className="mt-4 rounded-full border border-[rgba(16,32,53,0.1)] bg-ink-950 px-4 py-2 text-sm font-semibold text-paper-50 transition hover:-translate-y-0.5 hover:bg-ink-900 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={selectedFiles.length === 0 || uploadStatus === "processing"}
              onClick={() => {
                void handleUploadDocuments();
              }}
              type="button"
            >
              Process uploads
            </button>
          </div>
        </SurfaceCard>

        <SurfaceCard className="p-5" tone="paper">
          <SectionLabel>Session history</SectionLabel>
          <div className="mt-4 space-y-3">
            {workspaceHistory.length === 0 ? (
              <p className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 px-3 py-3 text-sm leading-7 text-ink-700">
                Sign in through the protected session bridge to persist
                workspace history across runs.
              </p>
            ) : (
              workspaceHistory.map((entry) => (
                <div
                  className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 px-3 py-3"
                  key={`${entry.createdAt}-${entry.query}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <CitationBadge
                      tone={
                        entry.status === "completed"
                          ? "verified"
                          : entry.status === "running"
                            ? "persuasive"
                            : "unverified"
                      }
                    >
                      {entry.status}
                    </CitationBadge>
                    <span className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-ink-700">
                      {entry.pipeline}
                    </span>
                  </div>
                  <p className="mt-3 text-sm font-semibold leading-7 text-ink-950">
                    {entry.query}
                  </p>
                  <p className="mt-2 text-xs uppercase tracking-[0.16em] text-ink-700">
                    {formatHistoryTimestamp(entry.createdAt)}
                  </p>
                </div>
              ))
            )}
          </div>
        </SurfaceCard>

        <SurfaceCard className="p-5" tone="paper">
          <div className="flex items-start justify-between gap-3">
            <div>
              <SectionLabel>Saved answers</SectionLabel>
              <p className="mt-3 text-sm leading-7 text-ink-700">
                Pin a structured answer to this workspace and export it as a
                research note.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
                onClick={handleSaveAnswer}
                type="button"
              >
                Save answer
              </button>
              <button
                className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
                onClick={handleExportAnswer}
                type="button"
              >
                Export markdown
              </button>
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {savedAnswers.length === 0 ? (
              <p className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 px-3 py-3 text-sm leading-7 text-ink-700">
                No saved answers yet. Run a query and pin the output here to
                keep it across reloads.
              </p>
            ) : (
              savedAnswers.map((entry) => (
                <button
                  className="w-full rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-white/72 px-3 py-3 text-left transition hover:border-[rgba(171,127,40,0.28)]"
                  key={entry.id}
                  onClick={() => {
                    setSelectedSavedAnswerId(entry.id);
                  }}
                  type="button"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <CitationBadge
                      tone={
                        entry.answer.overallStatus === "VERIFIED"
                          ? "verified"
                          : entry.answer.overallStatus === "UNCERTAIN"
                            ? "uncertain"
                            : "unverified"
                      }
                    >
                      {entry.answer.overallStatus}
                    </CitationBadge>
                    <span className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-ink-700">
                      {formatHistoryTimestamp(entry.savedAt)}
                    </span>
                  </div>
                  <p className="mt-3 text-sm font-semibold leading-7 text-ink-950">
                    {entry.query}
                  </p>
                </button>
              ))
            )}
          </div>
        </SurfaceCard>

        <SurfaceCard className="p-5" tone="muted">
          <SectionLabel>Open issues</SectionLabel>
          <ul className="mt-4 space-y-3 text-sm leading-7 text-ink-800">
            {workspaceContext.open_legal_issues.map((issue) => (
              <li
                className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/75 px-3 py-3"
                key={issue}
              >
                {issue}
              </li>
            ))}
          </ul>
        </SurfaceCard>
      </div>

      <div className="space-y-4">
        <SurfaceCard className="p-6 sm:p-7" tone="paper">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-3">
              <SectionLabel>Research workbench</SectionLabel>
              <h2 className="text-3xl text-ink-950">
                Ask a grounded question against this case file.
              </h2>
              <p className="max-w-3xl text-sm leading-7 text-ink-700">
                The shell is now ready for real research flow: case context on
                the left, query and answer path in the center, source evidence
                on the right.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <CitationBadge tone="binding">Workspace ready</CitationBadge>
              <CitationBadge
                tone={streamState.structuredAnswer ? "verified" : "persuasive"}
              >
                {streamState.structuredAnswer ? "Live answer" : "Demo answer fallback"}
              </CitationBadge>
              <button
                className="rounded-full border border-[rgba(16,32,53,0.1)] bg-white/78 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:-translate-y-0.5 hover:border-[rgba(171,127,40,0.28)]"
                onClick={() => {
                  setIsTransparencyOpen(true);
                }}
                type="button"
              >
                Open transparency log
              </button>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap gap-2">
            {workspaceContext.charges_sections.map((section) => (
              <CitationBadge key={section} tone="uncertain">
                {section}
              </CitationBadge>
            ))}
            {workspaceContext.bnss_equivalents.map((section) => (
              <CitationBadge key={section} tone="verified">
                {section}
              </CitationBadge>
            ))}
            <CitationBadge tone="persuasive">
              {transparencyEventCount} live events
            </CitationBadge>
          </div>
        </SurfaceCard>

        <BootstrapQueryConsole
          buttonLabel="Start Research"
          defaultQuery={defaultWorkspaceQuery}
          description="Submit a live query from the workspace and watch ordered backend steps resolve into an answer stream. The same SSE contract now powers the actual center lane."
          heading="Live process display for workspace research."
          sectionLabel="Live research display"
          showContractNotes={false}
          showQueryInput
          suggestedQueries={suggestedQueries}
          workspaceId={workspaceContext.case_id}
          onQuerySubmitted={setLastSubmittedQuery}
          onStateChange={setStreamState}
          requestHeaders={authHeaders}
        />

        <StructuredAnswerRenderer
          activeSourceId={activeSourceId}
          answer={activeAnswer}
          onSelectSource={handleSelectSource}
        />

        <CitationGraph
          activeSourceId={activeSourceId}
          answer={activeAnswer}
          onSelectSource={handleSelectSource}
        />

        <SurfaceCard className="p-5" tone="muted">
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <SectionLabel>Facts timeline</SectionLabel>
              <div className="mt-4 space-y-3">
                {workspaceContext.key_facts.map((fact) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/75 px-4 py-3"
                    key={`${fact.date}-${fact.label}`}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.2em] text-ink-700">
                      {fact.date ?? "Undated"}
                    </p>
                    <p className="mt-2 text-sm font-semibold text-ink-950">
                      {fact.label}
                    </p>
                    <p className="mt-2 text-sm leading-7 text-ink-800">
                      {fact.detail}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <SectionLabel>Prior orders</SectionLabel>
              <div className="mt-4 space-y-3">
                {[
                  ...workspaceContext.previous_orders,
                  ...workspaceContext.bail_history,
                ].map((order) => (
                  <div
                    className="rounded-[1rem] border border-[rgba(16,32,53,0.08)] bg-paper-50/75 px-4 py-3"
                    key={`${order.court}-${order.date}-${order.outcome}`}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.2em] text-ink-700">
                      {order.date ?? "Undated"} · {order.court}
                    </p>
                    <p className="mt-2 text-sm leading-7 text-ink-800">
                      {order.outcome}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </SurfaceCard>
      </div>

      <div className="space-y-4 xl:sticky xl:top-6">
        <SurfaceCard className="p-5" tone="ink">
          <div className="flex items-start justify-between gap-3">
            <div>
              <SectionLabel className="text-[rgba(244,236,221,0.72)]">
                Source viewer
              </SectionLabel>
              <h2 className="mt-3 text-2xl text-paper-50">
                Primary authority stays open while you research.
              </h2>
            </div>
            <CitationBadge tone="binding">Binding</CitationBadge>
          </div>

          <div className="mt-5 rounded-[1.2rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.06)] p-4">
            <p className="font-serif text-xl text-paper-50">
              {activeSourceCitation}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <CitationBadge
                tone={
                  activeSource?.status === "VERIFIED"
                    ? "verified"
                    : activeSource?.status === "UNCERTAIN"
                      ? "uncertain"
                      : "unverified"
                }
              >
                {activeSource?.status ?? "UNVERIFIED"}
              </CitationBadge>
              {activeSourceDocId ? (
                <CitationBadge tone="binding">{activeSourceDocId}</CitationBadge>
              ) : null}
              {activeFetchedSource ? (
                <CitationBadge tone="persuasive">
                  {activeFetchedSource.currentValidity}
                </CitationBadge>
              ) : null}
              {sourceViewerLoadingId === activeSource?.id ? (
                <CitationBadge tone="persuasive">Loading source</CitationBadge>
              ) : null}
            </div>
            <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.78)]">
              {activeSourceMessage ??
                "Select an inline citation badge from the answer to inspect the supporting source."}
            </p>
            {sourceViewerError ? (
              <p className="mt-3 text-sm leading-7 text-[rgba(242,177,172,0.82)]">
                {sourceViewerError}
              </p>
            ) : null}
          </div>

          <div className="mt-4 rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] p-4">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(244,236,221,0.6)]">
              Relevant passage
            </p>
            <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.84)]">
              {activeSourcePassage ??
                "No source passage is active yet."}
            </p>
          </div>

          {activeFetchedSource?.sourceUrl ? (
            <div className="mt-4 rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] p-4">
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(244,236,221,0.6)]">
                Canonical source
              </p>
              <a
                className="mt-3 block break-all text-sm leading-7 text-[rgba(252,247,239,0.84)] underline decoration-[rgba(244,236,221,0.36)] underline-offset-4"
                href={activeFetchedSource.sourceUrl}
                rel="noreferrer"
                target="_blank"
              >
                {activeFetchedSource.sourceUrl}
              </a>
            </div>
          ) : null}

          {activeAppealWarning ? (
            <div className="mt-4 rounded-[1rem] border border-[rgba(152,80,77,0.24)] bg-[rgba(152,80,77,0.08)] p-4">
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(242,177,172,0.72)]">
                Appeal warning
              </p>
              <p className="mt-3 text-sm leading-7 text-[rgba(252,247,239,0.82)]">
                {activeAppealWarning}
              </p>
            </div>
          ) : null}

          <div className="mt-5">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-[rgba(244,236,221,0.6)]">
              Also cited in answer
            </p>
            <ul className="mt-3 space-y-3 text-sm leading-7 text-[rgba(252,247,239,0.82)]">
              {relatedSources.slice(0, 3).map((source) => (
                <li key={source.id}>
                  <button
                    className="w-full rounded-[1rem] border border-[rgba(244,236,221,0.12)] bg-[rgba(252,247,239,0.04)] px-3 py-3 text-left transition hover:border-[rgba(207,177,112,0.32)]"
                    onClick={() => {
                      handleSelectSource(source);
                    }}
                    type="button"
                  >
                    {source.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </SurfaceCard>

        <SurfaceCard className="p-5" tone="paper">
          <SectionLabel>Acts in play</SectionLabel>
          <div className="mt-4 flex flex-wrap gap-2">
            {workspaceContext.statutes_involved.map((statute) => (
              <CitationBadge key={statute} tone="persuasive">
                {statute}
              </CitationBadge>
            ))}
          </div>
        </SurfaceCard>
      </div>

      <TransparencyDrawer
        isOpen={isTransparencyOpen}
        onClose={() => {
          setIsTransparencyOpen(false);
        }}
        streamState={streamState}
      />
    </div>
  );
}
