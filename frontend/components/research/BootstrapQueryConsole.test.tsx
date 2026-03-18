import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

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
    render(<BootstrapQueryConsole />);

    fireEvent.click(screen.getByRole("button", { name: /Run Stream Demo/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(1);
      expect(FakeEventSource.instances).toHaveLength(1);
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
            sequence: 2,
            emitted_at: "2026-03-16T00:00:01Z",
          }),
        }),
      );
      source.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "COMPLETE",
            sequence: 3,
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
    });
  });
});
