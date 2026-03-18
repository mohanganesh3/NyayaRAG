type CitationTone =
  | "verified"
  | "uncertain"
  | "unverified"
  | "binding"
  | "persuasive";

type CitationBadgeProps = {
  children: React.ReactNode;
  className?: string;
  tone: CitationTone;
};

export function CitationBadge({
  children,
  className,
  tone,
}: CitationBadgeProps) {
  return (
    <span
      className={["citation-badge", `citation-badge-${tone}`, className]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </span>
  );
}
