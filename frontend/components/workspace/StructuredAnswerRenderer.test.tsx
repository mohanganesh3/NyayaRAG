import { fireEvent, render, screen } from "@testing-library/react";

import {
  collectStructuredAnswerSources,
  demoStructuredAnswer,
} from "../../lib/structured-answer";
import { StructuredAnswerRenderer } from "./StructuredAnswerRenderer";

describe("StructuredAnswerRenderer", () => {
  it("renders answer sections and activates source bindings from inline citations", () => {
    const sources = collectStructuredAnswerSources(demoStructuredAnswer);
    const onSelectSource = vi.fn();

    render(
      <StructuredAnswerRenderer
        activeSourceId={sources[0]?.id ?? null}
        answer={demoStructuredAnswer}
        onSelectSource={onSelectSource}
      />,
    );

    expect(screen.getByText(/Legal Position/i)).toBeInTheDocument();
    expect(screen.getByText(/Verification Status/i)).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: /Arnesh Kumar/i,
      }),
    );

    expect(onSelectSource).toHaveBeenCalledWith(
      expect.objectContaining({
        label: "Arnesh Kumar",
      }),
    );
  });
});
