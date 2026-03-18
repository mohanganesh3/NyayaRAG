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
    expect(screen.getByRole("button", { name: /Run Research Demo/i })).toBeInTheDocument();
  });
});
