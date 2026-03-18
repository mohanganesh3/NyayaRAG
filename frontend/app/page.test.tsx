import { render, screen } from "@testing-library/react";

import HomePage from "./page";

describe("HomePage", () => {
  it("renders the proof-oriented landing page content", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", {
        name: /Trust-first Indian legal research starts with architecture/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Citation Fabrication Allowance/i)).toBeInTheDocument();
    expect(screen.getByText(/Trust Dashboard Preview/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Lower than legacy research, without weakening verification/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/20 queries per day/i)).toBeInTheDocument();
    expect(screen.getByText(/Shared research workspaces/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Manage plans and billing/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open full trust page/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open launch assets/i })).toBeInTheDocument();
  });
});
