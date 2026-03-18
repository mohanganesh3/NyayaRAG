export type StreamEventType =
  | "STEP_START"
  | "STEP_COMPLETE"
  | "STEP_ERROR"
  | "AGENT_LOG"
  | "TOKEN"
  | "CITATION_RESOLVED"
  | "COMPLETE";

type StreamEventBase = {
  sequence: number;
  emitted_at: string;
};

export type StepStartEvent = StreamEventBase & {
  type: "STEP_START";
  step: string;
};

export type StepCompleteEvent = StreamEventBase & {
  type: "STEP_COMPLETE";
  step: string;
  data?: Record<string, unknown> | null;
};

export type StepErrorEvent = StreamEventBase & {
  type: "STEP_ERROR";
  step: string;
  error: string;
};

export type AgentLogEvent = StreamEventBase & {
  type: "AGENT_LOG";
  agent: string;
  message: string;
};

export type TokenEvent = StreamEventBase & {
  type: "TOKEN";
  token: string;
};

export type CitationResolvedEvent = StreamEventBase & {
  type: "CITATION_RESOLVED";
  placeholder: string;
  citation: string;
  status: string;
};

export type CompleteEvent = StreamEventBase & {
  type: "COMPLETE";
  confidence: number;
  metrics: Record<string, unknown>;
};

export type QueryStreamEvent =
  | StepStartEvent
  | StepCompleteEvent
  | StepErrorEvent
  | AgentLogEvent
  | TokenEvent
  | CitationResolvedEvent
  | CompleteEvent;

export type QueryAcceptedResponse = {
  success: true;
  data: {
    query_id: string;
    status: "accepted";
    stream_url: string;
    created_at: string;
  };
};

export type ErrorResponse = {
  success: false;
  error: {
    code: string;
    message: string;
    detail?: unknown;
  };
};

export type QueryStreamState = {
  steps: Array<{
    name: string;
    status: "running" | "completed" | "error";
    detail?: string;
  }>;
  output: string;
  status: "idle" | "connecting" | "streaming" | "complete" | "error";
  errorMessage: string | null;
  confidence: number | null;
};

export function createInitialQueryStreamState(): QueryStreamState {
  return {
    steps: [],
    output: "",
    status: "idle",
    errorMessage: null,
    confidence: null,
  };
}

export function applyQueryStreamEvent(
  state: QueryStreamState,
  event: QueryStreamEvent,
): QueryStreamState {
  switch (event.type) {
    case "STEP_START":
      return {
        ...state,
        status: "streaming",
        steps: [...state.steps, { name: event.step, status: "running" }],
      };
    case "STEP_COMPLETE":
      return {
        ...state,
        status: "streaming",
        steps: state.steps.map((step) =>
          step.name === event.step
            ? {
                ...step,
                status: "completed",
                detail: event.data ? JSON.stringify(event.data) : undefined,
              }
            : step,
        ),
      };
    case "STEP_ERROR":
      return {
        ...state,
        status: "error",
        errorMessage: event.error,
        steps: state.steps.map((step) =>
          step.name === event.step
            ? { ...step, status: "error", detail: event.error }
            : step,
        ),
      };
    case "TOKEN":
      return {
        ...state,
        status: "streaming",
        output: `${state.output}${event.token}`,
      };
    case "COMPLETE":
      return {
        ...state,
        status: "complete",
        confidence: event.confidence,
      };
    default:
      return state;
  }
}

