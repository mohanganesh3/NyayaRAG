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
    expect(screen.getByLabelText(/Query input/i)).toBeInTheDocument();
    expect(screen.getByText(/Relevant passage/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start Research/i })).toBeInTheDocument();
    expect(
      screen.getByText(/No streamed answer yet\. Start the run to watch the response fade in as tokens arrive\./i),
    ).toBeInTheDocument();
  });
});
