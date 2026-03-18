import {
  applyQueryStreamEvent,
  createInitialQueryStreamState,
} from "./query-stream";

describe("query stream reducer", () => {
  it("builds step and output state from stream events", () => {
    let state = createInitialQueryStreamState();

    state = applyQueryStreamEvent(state, {
      type: "STEP_START",
      step: "Analyzing query...",
      sequence: 1,
      emitted_at: "2026-03-16T00:00:00Z",
    });
    state = applyQueryStreamEvent(state, {
      type: "STEP_COMPLETE",
      step: "Analyzing query...",
      sequence: 2,
      emitted_at: "2026-03-16T00:00:01Z",
      data: { pipeline: "bootstrap-demo" },
    });
    state = applyQueryStreamEvent(state, {
      type: "TOKEN",
      token: "NyayaRAG",
      sequence: 3,
      emitted_at: "2026-03-16T00:00:02Z",
    });
    state = applyQueryStreamEvent(state, {
      type: "COMPLETE",
      sequence: 4,
      emitted_at: "2026-03-16T00:00:03Z",
      confidence: 1,
      metrics: { mode: "dummy" },
    });

    expect(state.steps[0]).toMatchObject({
      name: "Analyzing query...",
      status: "completed",
    });
    expect(state.output).toBe("NyayaRAG");
    expect(state.status).toBe("complete");
    expect(state.confidence).toBe(1);
  });
});

