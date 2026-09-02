import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { Totals } from "@/lib/types";

const numberFormatter = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export function formatNumber(value: number) {
  return numberFormatter.format(value);
}

export function ProgressCard({
  label,
  unit,
  consumed,
  goal,
  remaining,
  percent,
}: {
  label: string;
  unit: string;
  consumed: number;
  goal: number | null;
  remaining: number | null;
  percent: number;
}) {
  const barValue = Math.min(Math.max(percent, 0), 100);
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-baseline justify-between gap-2 text-sm font-medium text-muted-foreground">
          <span>{label}</span>
          <strong className="whitespace-nowrap text-xl font-semibold text-foreground">
            {formatNumber(consumed)} {unit}
          </strong>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <Progress value={barValue} aria-label={`${label}: ${formatNumber(percent)}%`} />
        {goal === null ? (
          <p className="text-xs text-muted-foreground">Sem meta definida</p>
        ) : (
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="whitespace-nowrap">
              Meta {formatNumber(goal)} {unit}
            </span>
            <span className="whitespace-nowrap font-medium text-foreground">
              {formatNumber(percent)}%
            </span>
          </div>
        )}
        {remaining !== null && (
          <p className="text-xs text-muted-foreground">
            {formatNumber(remaining)} {unit} restante
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function totalsForProgress(totals: Totals) {
  return [
    { key: "kcal", label: "Calorias", unit: "kcal", value: totals.kcal },
    { key: "protein_g", label: "Proteína", unit: "g", value: totals.protein_g },
    { key: "carbs_g", label: "Carboidrato", unit: "g", value: totals.carbs_g },
    { key: "fat_g", label: "Gordura", unit: "g", value: totals.fat_g },
    { key: "fiber_g", label: "Fibra", unit: "g", value: totals.fiber_g },
  ] as const;
}
