import { render, screen } from "@testing-library/react";

import { CitationBadge } from "./CitationBadge";

describe("CitationBadge", () => {
  it("renders the requested citation state variant", () => {
    render(<CitationBadge tone="verified">Verified</CitationBadge>);

    const badge = screen.getByText("Verified");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("citation-badge-verified");
  });
});
