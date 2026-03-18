import { render, screen } from "@testing-library/react";

import BillingPage from "./page";

describe("BillingPage", () => {
  it("renders the billing plan, catalog, and invoice history surfaces", () => {
    render(<BillingPage />);

    expect(
      screen.getByRole("heading", {
        name: /Plan enforcement, checkout flow, and invoice history\./i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Current plan/i)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /Advocate Pro/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Razorpay-backed plans mapped to product entitlements\./i),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/Advocate Pro monthly subscription/i),
    ).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Back to landing page/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open workspace/i })).toBeInTheDocument();
  });
});
