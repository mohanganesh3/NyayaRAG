import { render, screen } from "@testing-library/react";

import { ProcessPanel } from "./ProcessPanel";

describe("ProcessPanel", () => {
  it("renders step states in the legal process timeline", () => {
    render(
      <ProcessPanel
        emptyMessage="Nothing yet."
        eyebrow="Live process"
        steps={[
          {
            name: "Analyzing query...",
            status: "completed",
            detail: '{"pipeline":"hybrid_rag"}',
          },
        ]}
        title="Verification timeline"
      />,
    );

    expect(screen.getByText("Verification timeline")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("Analyzing query...")).toBeInTheDocument();
  });
});
