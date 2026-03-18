type SurfaceTone = "paper" | "ink" | "muted";

type SurfaceCardProps = {
  children: React.ReactNode;
  className?: string;
  tone?: SurfaceTone;
};

export function SurfaceCard({
  children,
  className,
  tone = "paper",
}: SurfaceCardProps) {
  return (
    <div
      className={[
        "surface-card",
        `surface-card-${tone}`,
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </div>
  );
}
