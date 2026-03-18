import { fireEvent, render, screen } from "@testing-library/react";

import { demoWorkspaceContext } from "../../lib/workspace";
import { WorkspaceShell } from "./WorkspaceShell";

describe("WorkspaceShell", () => {
  it("renders persisted case context fields and source viewer content", () => {
    render(<WorkspaceShell context={demoWorkspaceContext} />);

    expect(screen.getByText(/Arjun Rao v\. State of Karnataka/i)).toBeInTheDocument();
    expect(screen.getByText(/Criminal Petition No\. 4812\/2026/i)).toBeInTheDocument();
    expect(screen.getByText(/Uploaded documents/i)).toBeInTheDocument();
    expect(screen.getByText(/Live research display/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open transparency log/i })).toBeInTheDocument();
    expect(screen.getByText(/Citation graph/i)).toBeInTheDocument();
    expect(
      screen.getByText(
        /Personal liberty requires the court to examine whether the prosecution has shown concrete investigative necessity before permitting arrest in anticipatory bail matters\./i,
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getAllByRole("button", {
        name: /Arnesh Kumar/i,
      })[0],
    );

    expect(
      screen.getByText(
        /Arrest cannot be routine, and the investigating officer must justify why custody is necessary on the facts of the case\./i,
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: /Citation graph node BNSS 482/i,
      }),
    );

    expect(
      screen.getByText(
        /BNSS Section 482 carries forward the anticipatory bail framework for the post-cutover criminal procedure regime\./i,
      ),
    ).toBeInTheDocument();
  });
});
