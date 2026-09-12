"use client";

import { ArrowDown, ArrowUp, Flame, Utensils } from "lucide-react";

import { CalorieDistributionChart, MealCaloriesChart } from "@/components/analytics-charts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/components/progress-card";
import type { DailySummary, RangeSummary } from "@/lib/types";

function variation(current: number, average: number) {
  return average ? ((current - average) / average) * 100 : null;
}

function Comparison({ label, current, average, unit }: { label: string; current: number; average: number; unit: string }) {
  const change = variation(current, average);
  const above = (change ?? 0) >= 0;
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-semibold">{formatNumber(current)} {unit}</p>
      <p className="text-xs text-muted-foreground">Média: {formatNumber(average)} {unit}</p>
      {change === null ? <p className="mt-1 text-xs text-muted-foreground">Sem média comparável</p> : (
        <p className={`mt-1 flex items-center gap-1 text-xs ${above ? "text-amber-400" : "text-emerald-400"}`}>
          {above ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}
          {formatNumber(Math.abs(change))}% {above ? "acima" : "abaixo"}
        </p>
      )}
    </div>
  );
}

export function AnalyticsComparison({
  summary,
  week,
  mealData,
  missingMeals,
  estimatedPerMeal,
  streak,
  recordedDays,
}: {
  summary: DailySummary;
  week: RangeSummary;
  mealData: { meal: string; kcal: number }[];
  missingMeals: string[];
  estimatedPerMeal: number | null;
  streak: number;
  recordedDays: number;
}) {
  const proteinKcal = summary.consumed.protein_g * 4;
  const carbsKcal = summary.consumed.carbs_g * 4;
  const fatKcal = summary.consumed.fat_g * 9;
  return (
    <section className="mt-6 grid gap-4 lg:grid-cols-2" aria-label="Análises do dia">
      <Card>
        <CardHeader><CardTitle>Distribuição calórica</CardTitle></CardHeader>
        <CardContent><CalorieDistributionChart protein={proteinKcal} carbs={carbsKcal} fat={fatKcal} /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Calorias por refeição</CardTitle></CardHeader>
        <CardContent><MealCaloriesChart data={mealData} /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Hoje x média de 7 dias</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <Comparison label="Calorias" current={summary.consumed.kcal} average={week.averages.kcal} unit="kcal" />
          <Comparison label="Proteína" current={summary.consumed.protein_g} average={week.averages.protein_g} unit="g" />
        </CardContent>
      </Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Utensils className="size-4" />Restante do dia</CardTitle></CardHeader>
          <CardContent>
            {summary.goal === null ? <p className="text-sm text-muted-foreground">Defina uma meta para estimar o restante do dia.</p> :
              missingMeals.length === 0 ? <p className="text-sm text-muted-foreground">Todas as refeições já têm registro.</p> :
                <div className="space-y-1 text-sm"><p><strong>{formatNumber(Math.max(0, summary.remaining?.kcal ?? 0))} kcal</strong> restantes</p><p className="text-muted-foreground">≈ {formatNumber(estimatedPerMeal ?? 0)} kcal por refeição: {missingMeals.join(", ")}.</p></div>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Flame className="size-4" />Sequência de registros</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-semibold">{streak} {streak === 1 ? "dia" : "dias"}</p><p className="text-sm text-muted-foreground">{recordedDays} de 30 dias com registro.</p></CardContent>
        </Card>
      </div>
    </section>
  );
}
