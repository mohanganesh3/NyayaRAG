import { render, screen } from "@testing-library/react";

import TrustPage from "./page";

describe("TrustPage", () => {
  it("renders the public trust benchmark page", async () => {
    render(await TrustPage());

    expect(
      screen.getByRole("heading", {
        name: /Measured trust has to stay public\./i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Trust snapshot/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Benchmark rendering stays close to the backend contract\./i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Citation existence rate/i)).toBeInTheDocument();
    expect(screen.getByText(/Weekly public benchmark/i)).toBeInTheDocument();
    expect(screen.getByText(/Preview fallback/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to landing page/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open workspace/i })).toBeInTheDocument();
  });
});
