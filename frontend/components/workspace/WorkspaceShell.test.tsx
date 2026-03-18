import { render, screen } from "@testing-library/react";

import { demoWorkspaceContext } from "../../lib/workspace";
import { WorkspaceShell } from "./WorkspaceShell";

describe("WorkspaceShell", () => {
  it("renders persisted case context fields and source viewer content", () => {
    render(<WorkspaceShell context={demoWorkspaceContext} />);

    expect(screen.getByText(/Arjun Rao v\. State of Karnataka/i)).toBeInTheDocument();
    expect(screen.getByText(/Criminal Petition No\. 4812\/2026/i)).toBeInTheDocument();
    expect(screen.getByText(/Uploaded documents/i)).toBeInTheDocument();
    expect(screen.getByText(/Live research display/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Siddharam Satlingappa Mhetre v State of Maharashtra/i),
    ).toBeInTheDocument();
  });
});
