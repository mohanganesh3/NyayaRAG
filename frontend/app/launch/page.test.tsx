import { render, screen } from "@testing-library/react";

import LaunchPage from "./page";

describe("LaunchPage", () => {
  it("renders the launch assets page", () => {
    render(<LaunchPage />);

    expect(
      screen.getByRole("heading", {
        name: /Launch proof has to be as disciplined as product proof\./i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/^Comparison demo$/i)).toBeInTheDocument();
    expect(screen.getByText(/^Benchmark storytelling$/i)).toBeInTheDocument();
    expect(screen.getByText(/^Distribution checklist$/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open trust page/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open workspace/i })).toBeInTheDocument();
  });
});
