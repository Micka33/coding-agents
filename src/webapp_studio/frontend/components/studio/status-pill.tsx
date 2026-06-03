import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type StatusPillProps = {
  label: string
  tone?: "emerald" | "amber" | "rose" | "sky" | "slate"
}

const tones = {
  emerald: "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  amber: "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200",
  rose: "border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200",
  sky: "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-200",
  slate: "border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200",
}

export function StatusPill({ label, tone = "slate" }: StatusPillProps) {
  return (
    <Badge className={cn("rounded-md border px-2 py-0.5 font-normal", tones[tone])}>
      {label}
    </Badge>
  )
}
