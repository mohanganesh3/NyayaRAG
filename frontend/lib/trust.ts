export type FrontendTrustSnapshot = {
  benchmarkName: string;
  benchmarkVersion: string | null;
  measuredAt: string;
  metrics: Record<string, number>;
  notes: string | null;
  payload: Record<string, unknown> | null;
  queryCount: number;
  runId: string;
  suiteName: string;
};

export type FrontendTrustPageData = {
  apiBaseUrl: string;
  snapshot: FrontendTrustSnapshot;
  source: "fallback" | "live";
};

type BackendTrustResponse = {
  data: {
    benchmark_name: string;
    benchmark_version: string | null;
    measured_at: string;
    metrics: Record<string, number>;
    notes: string | null;
    payload: Record<string, unknown> | null;
    query_count: number;
    run_id: string;
    suite_name: string;
  };
  success: true;
};

const metricLabels: Record<string, string> = {
  amendment_awareness_rate: "Amendment awareness rate",
  appeal_chain_accuracy: "Appeal-chain accuracy",
  bns_bnss_bsa_awareness: "BNS / BNSS / BSA awareness",
  citation_accuracy_rate: "Citation accuracy rate",
  citation_existence_rate: "Citation existence rate",
  jurisdiction_binding_accuracy: "Jurisdiction binding accuracy",
  multi_hop_completeness: "Multi-hop completeness",
  temporal_validity_rate: "Temporal validity rate",
};

const fallbackSnapshot: FrontendTrustSnapshot = {
  runId: "trust-preview-2026-03-19",
  suiteName: "India Legal Evaluation Suite",
  benchmarkName: "Weekly public benchmark",
  benchmarkVersion: "preview-1",
  measuredAt: "2026-03-19T09:00:00Z",
  queryCount: 2000,
  metrics: {
    citation_existence_rate: 1,
    citation_accuracy_rate: 0.987,
    appeal_chain_accuracy: 1,
    jurisdiction_binding_accuracy: 1,
    temporal_validity_rate: 1,
    amendment_awareness_rate: 1,
    multi_hop_completeness: 0.942,
    bns_bnss_bsa_awareness: 1,
  },
  notes:
    "Preview snapshot shown when the backend trust route is unavailable. The public page switches to measured backend data automatically.",
  payload: {
    comparison_baseline: "Westlaw AI 66.0% citation existence equivalent",
    publication_mode: "preview_fallback",
  },
};

function isBackendTrustResponse(value: unknown): value is BackendTrustResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const maybe = value as Partial<BackendTrustResponse>;
  return Boolean(
    maybe.success === true &&
      maybe.data &&
      typeof maybe.data.run_id === "string" &&
      typeof maybe.data.suite_name === "string" &&
      typeof maybe.data.benchmark_name === "string" &&
      typeof maybe.data.measured_at === "string" &&
      typeof maybe.data.query_count === "number" &&
      typeof maybe.data.metrics === "object" &&
      maybe.data.metrics !== null,
  );
}

export function formatTrustMetricValue(value: number): string {
  if (value >= 0 && value <= 1) {
    return `${(value * 100).toFixed(1)}%`;
  }

  return value.toLocaleString("en-IN");
}

export function formatTrustTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(new Date(value));
}

export function getTrustMetricLabel(metricKey: string): string {
  return metricLabels[metricKey] ?? metricKey.replaceAll("_", " ");
}

export function getDisplayTrustMetrics(snapshot: FrontendTrustSnapshot) {
  return Object.entries(snapshot.metrics).map(([key, value]) => ({
    key,
    label: getTrustMetricLabel(key),
    value: formatTrustMetricValue(value),
  }));
}

export async function getTrustPageData(): Promise<FrontendTrustPageData> {
  const apiBaseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  if (process.env.NODE_ENV === "test") {
    return {
      apiBaseUrl,
      snapshot: fallbackSnapshot,
      source: "fallback",
    };
  }

  try {
    const response = await fetch(`${apiBaseUrl}/api/trust`, {
      cache: "no-store",
    });

    if (response.ok) {
      const payload: unknown = await response.json();

      if (isBackendTrustResponse(payload)) {
        return {
          apiBaseUrl,
          source: "live",
          snapshot: {
            runId: payload.data.run_id,
            suiteName: payload.data.suite_name,
            benchmarkName: payload.data.benchmark_name,
            benchmarkVersion: payload.data.benchmark_version,
            measuredAt: payload.data.measured_at,
            queryCount: payload.data.query_count,
            metrics: payload.data.metrics,
            notes: payload.data.notes,
            payload: payload.data.payload,
          },
        };
      }
    }
  } catch {
    // Fall back to a stable preview snapshot when the backend route is unavailable.
  }

  return {
    apiBaseUrl,
    snapshot: fallbackSnapshot,
    source: "fallback",
  };
}
