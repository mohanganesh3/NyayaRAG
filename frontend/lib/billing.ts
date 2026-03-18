import type { FrontendAuthSession } from "./auth-session";

export type FrontendPricingTier = {
  badge?: string;
  cadence: string;
  code: "free" | "advocate_pro" | "chamber_pro";
  name: string;
  points: string[];
  price: string;
  tone: "paper" | "ink" | "muted";
};

export type FrontendBillingSummary = {
  cadence: string;
  checkoutEnabled: boolean;
  currentPlanCode: FrontendPricingTier["code"];
  currentPlanName: string;
  dailyQueryLimit: number | null;
  nextInvoiceDate: string | null;
  price: string;
  queriesRemainingToday: number | null;
  workspaceAccess: boolean;
};

export type FrontendBillingInvoice = {
  amount: string;
  description: string;
  issuedAt: string;
  status: "paid" | "issued" | "failed";
};

export type FrontendBillingPageData = {
  apiBaseUrl: string;
  billingSummary: FrontendBillingSummary;
  invoices: FrontendBillingInvoice[];
  pricingTiers: FrontendPricingTier[];
  source: "fallback" | "live";
};

type BackendBillingPlan = {
  cadence: string;
  code: FrontendPricingTier["code"];
  currency: string;
  daily_query_limit: number | null;
  features: string[];
  included_seats: number;
  max_active_workspaces: number | null;
  name: string;
  price_minor: number;
  workspace_access: boolean;
};

type BackendBillingPlansResponse = {
  data: BackendBillingPlan[];
  success: true;
};

type BackendBillingSubscriptionResponse = {
  data: {
    cadence: string;
    current_period_end: string | null;
    daily_query_limit: number | null;
    plan_code: FrontendPricingTier["code"];
    plan_name: string;
    price_minor: number;
    queries_remaining_today: number | null;
    status: string;
    workspace_access: boolean;
  };
  success: true;
};

type BackendBillingHistoryResponse = {
  data: Array<{
    amount_minor: number;
    currency: string;
    description: string | null;
    issued_at: string | null;
    status: "paid" | "issued" | "failed";
  }>;
  success: true;
};

export const pricingTiers: FrontendPricingTier[] = [
  {
    code: "free",
    name: "Free",
    price: "₹0",
    cadence: "/month",
    tone: "paper",
    points: [
      "20 queries per day",
      "Supreme Court + High Courts",
      "Basic citation verification",
      "No document upload",
    ],
  },
  {
    code: "advocate_pro",
    name: "Advocate Pro",
    price: "₹799",
    cadence: "/month",
    tone: "ink",
    badge: "Most practical",
    points: [
      "Unlimited queries",
      "All courts + tribunals + bare acts",
      "Upload up to 5 live case workspaces",
      "Citation graph and export workflow",
    ],
  },
  {
    code: "chamber_pro",
    name: "Chamber Pro",
    price: "₹2,499",
    cadence: "/month",
    tone: "muted",
    points: [
      "5 seats included",
      "Shared research workspaces",
      "Priority support",
      "API access and team history",
    ],
  },
];

function formatMinorCurrency(amountMinor: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    currency,
    style: "currency",
    maximumFractionDigits: 0,
  }).format(amountMinor / 100);
}

function formatCadence(cadence: string): string {
  return `/${cadence}`;
}

function isBackendBillingPlansResponse(
  value: unknown,
): value is BackendBillingPlansResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const payload = value as Partial<BackendBillingPlansResponse>;
  return payload.success === true && Array.isArray(payload.data);
}

function isBackendBillingSubscriptionResponse(
  value: unknown,
): value is BackendBillingSubscriptionResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const payload = value as Partial<BackendBillingSubscriptionResponse>;
  return Boolean(
    payload.success === true &&
      payload.data &&
      typeof payload.data.plan_code === "string" &&
      typeof payload.data.plan_name === "string",
  );
}

function isBackendBillingHistoryResponse(
  value: unknown,
): value is BackendBillingHistoryResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const payload = value as Partial<BackendBillingHistoryResponse>;
  return payload.success === true && Array.isArray(payload.data);
}

function normalizePricingTiers(plans: BackendBillingPlan[]): FrontendPricingTier[] {
  return plans.map((plan) => ({
    badge:
      plan.code === "advocate_pro"
        ? "Most practical"
        : plan.code === "free"
          ? undefined
          : undefined,
    cadence: formatCadence(plan.cadence),
    code: plan.code,
    name: plan.name,
    points: plan.features,
    price: formatMinorCurrency(plan.price_minor, plan.currency),
    tone:
      plan.code === "advocate_pro"
        ? "ink"
        : plan.code === "chamber_pro"
          ? "muted"
          : "paper",
  }));
}

export function demoBillingSummaryForSession(
  session: FrontendAuthSession,
): FrontendBillingSummary {
  if (!session.isAuthenticated) {
    return {
      currentPlanCode: "free",
      currentPlanName: "Free",
      price: "₹0",
      cadence: "/month",
      dailyQueryLimit: 20,
      queriesRemainingToday: 20,
      workspaceAccess: false,
      nextInvoiceDate: null,
      checkoutEnabled: false,
    };
  }

  return {
    currentPlanCode: "advocate_pro",
    currentPlanName: "Advocate Pro",
    price: "₹799",
    cadence: "/month",
    dailyQueryLimit: null,
    queriesRemainingToday: null,
    workspaceAccess: true,
    nextInvoiceDate: "2026-04-18",
    checkoutEnabled: true,
  };
}

export function demoBillingInvoicesForSession(
  session: FrontendAuthSession,
): FrontendBillingInvoice[] {
  if (!session.isAuthenticated) {
    return [];
  }

  return [
    {
      description: "Advocate Pro monthly subscription",
      amount: "₹799",
      status: "paid",
      issuedAt: "2026-03-18",
    },
    {
      description: "Advocate Pro monthly subscription",
      amount: "₹799",
      status: "paid",
      issuedAt: "2026-02-18",
    },
  ];
}

export async function getBillingPageData(args: {
  authHeaders: Record<string, string>;
  authSession: FrontendAuthSession;
}): Promise<FrontendBillingPageData> {
  const apiBaseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  if (process.env.NODE_ENV === "test") {
    return {
      apiBaseUrl,
      billingSummary: demoBillingSummaryForSession(args.authSession),
      invoices: demoBillingInvoicesForSession(args.authSession),
      pricingTiers,
      source: "fallback",
    };
  }

  try {
    const plansResponse = await fetch(`${apiBaseUrl}/api/billing/plans`, {
      cache: "no-store",
    });
    const plansPayload: unknown = await plansResponse.json();

    if (!plansResponse.ok || !isBackendBillingPlansResponse(plansPayload)) {
      throw new Error("Billing plan catalog unavailable.");
    }

    const livePricingTiers = normalizePricingTiers(plansPayload.data);

    if (!args.authSession.isAuthenticated || Object.keys(args.authHeaders).length === 0) {
      return {
        apiBaseUrl,
        billingSummary: demoBillingSummaryForSession(args.authSession),
        invoices: [],
        pricingTiers: livePricingTiers,
        source: "live",
      };
    }

    const [subscriptionResponse, historyResponse] = await Promise.all([
      fetch(`${apiBaseUrl}/api/billing/subscription`, {
        cache: "no-store",
        headers: args.authHeaders,
      }),
      fetch(`${apiBaseUrl}/api/billing/history`, {
        cache: "no-store",
        headers: args.authHeaders,
      }),
    ]);

    const subscriptionPayload: unknown = await subscriptionResponse.json();
    const historyPayload: unknown = await historyResponse.json();

    if (
      !subscriptionResponse.ok ||
      !historyResponse.ok ||
      !isBackendBillingSubscriptionResponse(subscriptionPayload) ||
      !isBackendBillingHistoryResponse(historyPayload)
    ) {
      throw new Error("Billing session payload unavailable.");
    }

    return {
      apiBaseUrl,
      billingSummary: {
        cadence: formatCadence(subscriptionPayload.data.cadence),
        checkoutEnabled: subscriptionPayload.data.plan_code !== "free",
        currentPlanCode: subscriptionPayload.data.plan_code,
        currentPlanName: subscriptionPayload.data.plan_name,
        dailyQueryLimit: subscriptionPayload.data.daily_query_limit,
        nextInvoiceDate: subscriptionPayload.data.current_period_end,
        price: formatMinorCurrency(
          subscriptionPayload.data.price_minor,
          "INR",
        ),
        queriesRemainingToday: subscriptionPayload.data.queries_remaining_today,
        workspaceAccess: subscriptionPayload.data.workspace_access,
      },
      invoices: historyPayload.data.map((invoice) => ({
        amount: formatMinorCurrency(invoice.amount_minor, invoice.currency),
        description: invoice.description ?? "NyayaRAG subscription invoice",
        issuedAt: invoice.issued_at ?? "Not issued",
        status: invoice.status,
      })),
      pricingTiers: livePricingTiers,
      source: "live",
    };
  } catch {
    return {
      apiBaseUrl,
      billingSummary: demoBillingSummaryForSession(args.authSession),
      invoices: demoBillingInvoicesForSession(args.authSession),
      pricingTiers,
      source: "fallback",
    };
  }
}
