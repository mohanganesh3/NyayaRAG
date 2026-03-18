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
