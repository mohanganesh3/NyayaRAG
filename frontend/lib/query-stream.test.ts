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
      type: "ANSWER_READY",
      sequence: 6,
      emitted_at: "2026-03-16T00:00:02Z",
      answer: {
        query: "What are the strongest anticipatory bail arguments?",
        overall_status: "VERIFIED",
        sections: [
          {
            kind: "LEGAL_POSITION",
            title: "Legal Position",
            claims: [
              {
                text: "Liberty-first anticipatory bail reasoning is available.",
                status: "VERIFIED",
                reason: "Grounded in binding authority.",
                citation: "Siddharam Satlingappa Mhetre",
                source_passage: "Personal liberty requires concrete necessity.",
                appeal_warning: null,
                reretrieved: false,
                citation_badges: [],
              },
            ],
            status_items: [],
          },
        ],
      },
    });
    state = applyQueryStreamEvent(state, {
      type: "COMPLETE",
      sequence: 7,
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
    expect(state.structuredAnswer).toMatchObject({
      overallStatus: "VERIFIED",
      query: "What are the strongest anticipatory bail arguments?",
    });
    expect(state.structuredAnswer?.sections[0]?.claims[0]).toMatchObject({
      text: "Liberty-first anticipatory bail reasoning is available.",
      sourcePassage: "Personal liberty requires concrete necessity.",
    });

    state = applyQueryStreamEvent(state, { type: "RESET" });
    expect(state).toEqual(createInitialQueryStreamState());
  });
});
