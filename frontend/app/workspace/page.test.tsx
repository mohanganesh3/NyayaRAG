import { render, screen } from "@testing-library/react";

import WorkspacePage from "./page";

describe("WorkspacePage", () => {
  it("renders the three-panel workspace shell", () => {
    render(<WorkspacePage />);

    expect(
      screen.getByRole("heading", {
        name: /Three panels, one legal research flow/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Uploaded documents/i)).toBeInTheDocument();
    expect(screen.getByText(/Upload workspace files/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Query input/i)).toBeInTheDocument();
    expect(screen.getByText(/Relevant passage/i)).toBeInTheDocument();
    expect(screen.getByText(/Protected workspace/i)).toBeInTheDocument();
    expect(screen.getByText(/Session history/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Saved answers/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Manage billing/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start Research/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open transparency log/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save answer/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export markdown/i })).toBeInTheDocument();
    expect(screen.getByText(/Verification Status/i)).toBeInTheDocument();
    expect(screen.getByText(/Citation graph/i)).toBeInTheDocument();
    expect(
      screen.getByText(/No streamed answer yet\. Start the run to watch the response fade in as tokens arrive\./i),
    ).toBeInTheDocument();
  });
});
