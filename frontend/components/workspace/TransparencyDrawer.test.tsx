import { fireEvent, render, screen } from "@testing-library/react";

import {
  applyQueryStreamEvent,
  createInitialQueryStreamState,
} from "../../lib/query-stream";
import { TransparencyDrawer } from "./TransparencyDrawer";

describe("TransparencyDrawer", () => {
  it("renders actual stream logs, citation resolutions, and completion metrics", () => {
    let streamState = createInitialQueryStreamState();

    streamState = applyQueryStreamEvent(streamState, {
      type: "AGENT_LOG",
      agent: "VerificationAgent",
      message: "Re-checked resolved authorities.",
      sequence: 4,
      emitted_at: "2026-03-18T09:14:28Z",
    });
    streamState = applyQueryStreamEvent(streamState, {
      type: "CITATION_RESOLVED",
      placeholder: "[CITE: bail authority]",
      citation: "Siddharam Satlingappa Mhetre v State of Maharashtra",
      status: "VERIFIED",
      sequence: 5,
      emitted_at: "2026-03-18T09:14:29Z",
    });
    streamState = applyQueryStreamEvent(streamState, {
      type: "COMPLETE",
      confidence: 0.97,
      metrics: {
        agent_count: 7,
        pipeline: "agentic_rag",
      },
      sequence: 6,
      emitted_at: "2026-03-18T09:14:30Z",
    });

    const onClose = vi.fn();
    render(
      <TransparencyDrawer
        isOpen
        onClose={onClose}
        streamState={streamState}
      />,
    );

    expect(screen.getByText(/Re-checked resolved authorities\./i)).toBeInTheDocument();
    expect(
      screen.getByText(/Siddharam Satlingappa Mhetre v State of Maharashtra/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/agentic_rag/i)).toBeInTheDocument();
    expect(screen.getByText("0.97")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
