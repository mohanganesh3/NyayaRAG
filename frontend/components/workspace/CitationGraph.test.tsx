import { fireEvent, render, screen } from "@testing-library/react";

import { demoStructuredAnswer } from "../../lib/structured-answer";
import { CitationGraph } from "./CitationGraph";

describe("CitationGraph", () => {
  it("links source nodes back to structured answer authorities", () => {
    const onSelectSource = vi.fn();

    render(
      <CitationGraph
        activeSourceId={null}
        answer={demoStructuredAnswer}
        onSelectSource={onSelectSource}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: /Citation graph node Arnesh Kumar/i,
      }),
    );

    expect(onSelectSource).toHaveBeenCalledWith(
      expect.objectContaining({
        docId: "sc-arnesh-2014",
        label: "Arnesh Kumar",
      }),
    );
  });
});
