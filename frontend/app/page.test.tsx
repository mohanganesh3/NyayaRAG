import { render, screen } from "@testing-library/react";

import HomePage from "./page";

describe("HomePage", () => {
  it("renders the bootstrap message", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", {
        name: /Trust-first Indian legal research starts with architecture/i,
      }),
    ).toBeInTheDocument();
  });
});
