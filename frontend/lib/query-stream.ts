import {
  normalizeStructuredAnswer,
  type StructuredAnswer,
} from "./structured-answer";

export type StreamEventType =
  | "STEP_START"
  | "STEP_COMPLETE"
  | "STEP_ERROR"
  | "AGENT_LOG"
  | "TOKEN"
  | "CITATION_RESOLVED"
  | "ANSWER_READY"
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

export type AnswerReadyEvent = StreamEventBase & {
  type: "ANSWER_READY";
  answer: Record<string, unknown>;
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
  | AnswerReadyEvent
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

export type QueryStreamStep = {
  name: string;
  status: "running" | "completed" | "error";
  detail?: string;
};

export type QueryStreamAgentLog = {
  agent: string;
  emittedAt: string;
  message: string;
  sequence: number;
};

export type QueryStreamCitationResolution = {
  citation: string;
  emittedAt: string;
  placeholder: string;
  sequence: number;
  status: string;
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
  steps: QueryStreamStep[];
  output: string;
  status: "idle" | "connecting" | "streaming" | "complete" | "error";
  errorMessage: string | null;
  confidence: number | null;
  agentLogs: QueryStreamAgentLog[];
  citationResolutions: QueryStreamCitationResolution[];
  metrics: Record<string, unknown> | null;
  structuredAnswer: StructuredAnswer | null;
};

export function createInitialQueryStreamState(): QueryStreamState {
  return {
    steps: [],
    output: "",
    status: "idle",
    errorMessage: null,
    confidence: null,
    agentLogs: [],
    citationResolutions: [],
    metrics: null,
    structuredAnswer: null,
  };
}

export type QueryStreamAction = QueryStreamEvent | { type: "RESET" };

function buildStepDetail(
  stepName: string,
  data: Record<string, unknown> | null | undefined,
  matchedName?: string,
): string | undefined {
  const fragments: string[] = [];

  if (matchedName && matchedName !== stepName) {
    fragments.push(stepName);
  }

  if (data && Object.keys(data).length > 0) {
    fragments.push(JSON.stringify(data));
  }

  return fragments.length > 0 ? fragments.join(" · ") : undefined;
}

function updateStepState(
  steps: QueryStreamStep[],
  eventStep: string,
  status: QueryStreamStep["status"],
  detail?: string,
): QueryStreamStep[] {
  const exactIndex = [...steps]
    .map((step, index) => ({ index, step }))
    .reverse()
    .find(({ step }) => step.name === eventStep)?.index;

  if (exactIndex !== undefined) {
    return steps.map((step, index) =>
      index === exactIndex ? { ...step, status, detail } : step,
    );
  }

  const runningIndex = [...steps]
    .map((step, index) => ({ index, step }))
    .reverse()
    .find(({ step }) => step.status === "running")?.index;

  if (runningIndex !== undefined) {
    const runningStep = steps[runningIndex];
    return steps.map((step, index) =>
      index === runningIndex
        ? {
            ...step,
            status,
            detail: buildStepDetail(eventStep, undefined, runningStep.name) ?? detail,
          }
        : step,
    );
  }

  return [...steps, { name: eventStep, status, detail }];
}

export function applyQueryStreamEvent(
  state: QueryStreamState,
  event: QueryStreamAction,
): QueryStreamState {
  if (event.type === "RESET") {
    return createInitialQueryStreamState();
  }

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
        steps: updateStepState(
          state.steps,
          event.step,
          "completed",
          buildStepDetail(event.step, event.data),
        ),
      };
    case "STEP_ERROR":
      return {
        ...state,
        status: "error",
        errorMessage: event.error,
        steps: updateStepState(state.steps, event.step, "error", event.error),
      };
    case "AGENT_LOG":
      return {
        ...state,
        agentLogs: [
          ...state.agentLogs,
          {
            agent: event.agent,
            emittedAt: event.emitted_at,
            message: event.message,
            sequence: event.sequence,
          },
        ],
      };
    case "TOKEN":
      return {
        ...state,
        status: "streaming",
        output: `${state.output}${event.token}`,
      };
    case "ANSWER_READY":
      return {
        ...state,
        status: "streaming",
        structuredAnswer: normalizeStructuredAnswer(event.answer),
      };
    case "COMPLETE":
      return {
        ...state,
        status: "complete",
        confidence: event.confidence,
        metrics: event.metrics,
      };
    case "CITATION_RESOLVED":
      return {
        ...state,
        citationResolutions: [
          ...state.citationResolutions,
          {
            citation: event.citation,
            emittedAt: event.emitted_at,
            placeholder: event.placeholder,
            sequence: event.sequence,
            status: event.status,
          },
        ],
      };
    default:
      return state;
  }
}
