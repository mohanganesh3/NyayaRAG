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
      step: "Query analyzed",
      sequence: 2,
      emitted_at: "2026-03-16T00:00:01Z",
      data: { pipeline: "bootstrap-demo" },
    });
    state = applyQueryStreamEvent(state, {
      type: "AGENT_LOG",
      agent: "QueryAnalyzer",
      message: "Classified as hybrid_rag",
      sequence: 3,
      emitted_at: "2026-03-16T00:00:01Z",
    });
    state = applyQueryStreamEvent(state, {
      type: "TOKEN",
      token: "NyayaRAG",
      sequence: 4,
      emitted_at: "2026-03-16T00:00:02Z",
    });
    state = applyQueryStreamEvent(state, {
      type: "CITATION_RESOLVED",
      placeholder: "[CITE: bail authority]",
      citation: "Siddharam Satlingappa Mhetre v State of Maharashtra",
      status: "VERIFIED",
      sequence: 5,
      emitted_at: "2026-03-16T00:00:02Z",
    });
    state = applyQueryStreamEvent(state, {
      type: "COMPLETE",
      sequence: 6,
      emitted_at: "2026-03-16T00:00:03Z",
      confidence: 1,
      metrics: { mode: "dummy", pipeline: "hybrid_rag" },
    });

    expect(state.steps[0]).toMatchObject({
      name: "Analyzing query...",
      status: "completed",
    });
    expect(state.output).toBe("NyayaRAG");
    expect(state.status).toBe("complete");
    expect(state.confidence).toBe(1);
    expect(state.agentLogs[0]).toMatchObject({
      agent: "QueryAnalyzer",
    });
    expect(state.citationResolutions[0]).toMatchObject({
      status: "VERIFIED",
    });
    expect(state.metrics).toMatchObject({ pipeline: "hybrid_rag" });

    state = applyQueryStreamEvent(state, { type: "RESET" });
    expect(state).toEqual(createInitialQueryStreamState());
  });
});
