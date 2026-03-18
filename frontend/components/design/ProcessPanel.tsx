type ProcessStep = {
  name: string;
  status: "running" | "completed" | "error";
  detail?: string;
};

type ProcessPanelProps = {
  emptyMessage: string;
  eyebrow: string;
  steps: ProcessStep[];
  title: string;
};

const statusLabel: Record<ProcessStep["status"], string> = {
  running: "Running",
  completed: "Verified",
  error: "Error",
};

export function ProcessPanel({
  emptyMessage,
  eyebrow,
  steps,
  title,
}: ProcessPanelProps) {
  return (
    <div className="process-shell">
      <div className="process-header">
        <p className="process-eyebrow">{eyebrow}</p>
        <h3 className="process-title">{title}</h3>
      </div>

      <div className="mt-5 space-y-4 font-mono text-sm">
        {steps.length === 0 ? (
          <p className="text-[rgba(244,236,221,0.72)]">{emptyMessage}</p>
        ) : null}

        {steps.map((step) => (
          <div
            key={`${step.name}-${step.status}`}
            className={`process-step process-step-${step.status}`}
          >
            <p className="process-step-title">
              <span className="process-step-status">
                {statusLabel[step.status]}
              </span>
              {step.name}
            </p>
            {step.detail ? (
              <p className="process-step-detail">{step.detail}</p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
