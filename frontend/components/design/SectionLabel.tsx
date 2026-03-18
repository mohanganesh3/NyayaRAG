type SectionLabelProps = {
  children: React.ReactNode;
  className?: string;
};

export function SectionLabel({
  children,
  className,
}: SectionLabelProps) {
  return (
    <p className={["section-label", className].filter(Boolean).join(" ")}>
      {children}
    </p>
  );
}
