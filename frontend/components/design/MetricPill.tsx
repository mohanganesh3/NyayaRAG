type MetricTone = "ink" | "brass" | "teal";

type MetricPillProps = {
  label: string;
  value: string;
  className?: string;
  tone?: MetricTone;
};

export function MetricPill({
  label,
  value,
  className,
  tone = "brass",
}: MetricPillProps) {
  return (
    <div
      className={["metric-pill", `metric-pill-${tone}`, className]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="metric-pill-label">{label}</span>
      <span className="metric-pill-value">{value}</span>
    </div>
  );
}
