import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Mock } from "vitest";

import { BootstrapQueryConsole } from "./BootstrapQueryConsole";

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    return undefined;
  }
}

describe("BootstrapQueryConsole", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          query_id: "query-1",
          status: "accepted",
          stream_url: "/api/query/query-1/stream",
          created_at: "2026-03-16T00:00:00Z",
        },
      }),
    }) as unknown as typeof fetch;

    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("consumes and renders streamed query events", async () => {
    const onStateChange = vi.fn();
    const { container } = render(
      <BootstrapQueryConsole
        defaultQuery="What are the strongest anticipatory bail arguments?"
        onStateChange={onStateChange}
        showQueryInput
        suggestedQueries={[
          "What are the strongest anticipatory bail arguments?",
          "Which Supreme Court case should lead the note?",
        ]}
        requestHeaders={{ "X-Nyayarag-Dev-User-Id": "dev-advocate" }}
        workspaceId="demo-bail-001"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Run Stream Demo/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(1);
      expect(FakeEventSource.instances).toHaveLength(1);
    });
    expect(JSON.parse(String((global.fetch as Mock).mock.calls[0]?.[1]?.body))).toMatchObject({
      query: "What are the strongest anticipatory bail arguments?",
      workspace_id: "demo-bail-001",
    });
    expect((global.fetch as Mock).mock.calls[0]?.[1]?.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-Nyayarag-Dev-User-Id": "dev-advocate",
    });

    const source = FakeEventSource.instances[0];
    await act(async () => {
      source.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "STEP_START",
            step: "Analyzing query...",
            sequence: 1,
            emitted_at: "2026-03-16T00:00:00Z",
          }),
        }),
      );
      source.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "TOKEN",
            token: "NyayaRAG bootstrap stream ready.",
            sequence: 3,
            emitted_at: "2026-03-16T00:00:01Z",
          }),
        }),
      );
      source.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "AGENT_LOG",
            agent: "QueryAnalyzer",
            message: "Detected hybrid_rag route.",
            sequence: 4,
            emitted_at: "2026-03-16T00:00:01Z",
          }),
        }),
      );
      source.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "COMPLETE",
            sequence: 5,
            emitted_at: "2026-03-16T00:00:02Z",
            confidence: 1,
            metrics: { mode: "dummy" },
          }),
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText(/Analyzing query/i)).toBeInTheDocument();
      expect(
        screen.getByText(/NyayaRAG bootstrap stream ready\./i),
      ).toBeInTheDocument();
      expect(screen.getByText("1.00")).toBeInTheDocument();
      expect(screen.getByText(/Detected hybrid_rag route\./i)).toBeInTheDocument();
    });

    const latestState = onStateChange.mock.calls.at(-1)?.[0];
    expect(latestState?.agentLogs.at(-1)).toMatchObject({
      agent: "QueryAnalyzer",
      message: "Detected hybrid_rag route.",
    });
    expect(latestState?.metrics).toMatchObject({ mode: "dummy" });

    const stepTitles = Array.from(
      container.querySelectorAll(".process-step-title"),
    ).map((element) => element.textContent);
    expect(stepTitles[0]).toContain("Connecting to backend...");
    expect(stepTitles[1]).toContain("Analyzing query...");
  });
});
