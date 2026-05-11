import { cn } from "@/lib/utils";

type ProgressProps = {
  value?: number | null;
  className?: string;
};

export function Progress({ value, className }: ProgressProps) {
  const pct = typeof value === "number" ? Math.max(0, Math.min(100, value)) : null;
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-secondary", className)}>
      <div
        className={cn("h-full bg-primary transition-all", pct === null && "w-1/3 animate-pulse")}
        style={pct === null ? undefined : { width: `${pct}%` }}
      />
    </div>
  );
}

