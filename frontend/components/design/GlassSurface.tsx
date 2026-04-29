"use client";

import { ReactNode } from "react";

type GlassSurfaceProps = {
  children: ReactNode;
  className?: string;
  intensity?: "low" | "medium" | "high";
  interactive?: boolean;
};

export function GlassSurface({
  children,
  className = "",
  intensity = "medium",
  interactive = false,
}: GlassSurfaceProps) {
  const blurClasses = {
    low: "backdrop-blur-[6px] bg-white/40",
    medium: "backdrop-blur-[12px] bg-white/60",
    high: "backdrop-blur-[24px] bg-white/75",
  };

  const interactiveClasses = interactive
    ? "transition-all duration-300 hover:bg-white/80 hover:shadow-xl"
    : "";

  return (
    <div
      className={`
        relative overflow-hidden rounded-[1.5rem] border border-[rgba(16,32,53,0.08)] 
        shadow-[0_8px_32px_rgba(8,16,28,0.04)]
        ${blurClasses[intensity]} 
        ${interactiveClasses} 
        ${className}
      `}
    >
      {/* Subtle shine effect */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-white/40 to-transparent opacity-50" />
      
      <div className="relative z-10">{children}</div>
    </div>
  );
}
