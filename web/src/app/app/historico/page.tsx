import Link from "next/link";

import { CaloriesLineChart, MacroStackedChart } from "@/components/analytics-charts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiGet, getSession } from "@/lib/api";
import { dateInTimezone, dateLabel, shiftDate } from "@/lib/dates";
import { formatNumber } from "@/components/progress-card";
import type { RangeSummary, TopFood } from "@/lib/types";

const periodOptions = [7, 14, 30, 90] as const;

type PageProps = { searchParams: Promise<{ days?: string | string[] }> };

function percentageChange(current: number, previous: number) {
  return previous ? ((current - previous) / previous) * 100 : null;
}

function percentage(value: number | null) {
  return value === null ? "—" : `${formatNumber(value)}%`;
}

export default async function HistoryPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const requestedDays = Array.isArray(params.days) ? params.days[0] : params.days;
  const parsedDays = Number(requestedDays);
  const days = periodOptions.includes(parsedDays as (typeof periodOptions)[number]) ? parsedDays : 7;
  const session = await getSession();
  const end = dateInTimezone(session.user.timezone);
  const start = shiftDate(end, -days + 1);
  const previousEnd = shiftDate(start, -1);
  const previousStart = shiftDate(previousEnd, -days + 1);
  const [summary, previous, topFoods] = await Promise.all([
    apiGet<RangeSummary>("/api/summary/range", { from: start, to: end }),
    apiGet<RangeSummary>("/api/summary/range", { from: previousStart, to: previousEnd }),
    apiGet<TopFood[]>("/api/insights/top-foods", { from: start, to: end, limit: "10" }),
  ]);

  const goalDays = summary.days.filter((day) => day.goal !== null);
  const adherenceDays = goalDays.filter(
    (day) => Math.abs(day.consumed.kcal - day.goal!.kcal) <= day.goal!.kcal * 0.1,
  );
  const proteinGoalDays = goalDays.filter((day) => day.goal!.protein_g > 0);
  const proteinAchievement = proteinGoalDays.length
    ? proteinGoalDays.reduce(
        (total, day) => total + (day.consumed.protein_g / day.goal!.protein_g) * 100,
        0,
      ) / proteinGoalDays.length
    : null;
  const kcalChange = percentageChange(summary.averages.kcal, previous.averages.kcal);
  const proteinChange = percentageChange(summary.averages.protein_g, previous.averages.protein_g);

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-primary">Tendências</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Histórico</h1>
        </div>
        <div className="flex flex-wrap gap-2" aria-label="Período do histórico">
          {periodOptions.map((option) => (
            <Button key={option} variant={days === option ? "default" : "outline"} size="sm" asChild>
              <Link href={`/app/historico?days=${option}`}>{option} dias</Link>
            </Button>
          ))}
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Calorias por dia</CardTitle>
          <CardDescription>Consumo diário e meta vigente no período.</CardDescription>
        </CardHeader>
        <CardContent>
          <CaloriesLineChart data={summary.days.map((day) => ({
            date: day.date,
            label: day.date.slice(5).split("-").reverse().join("/"),
            kcal: day.consumed.kcal,
            goal: day.goal?.kcal ?? null,
          }))} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Macros por dia</CardTitle>
          <CardDescription>Gramas de proteína, carboidrato e gordura registrados.</CardDescription>
        </CardHeader>
        <CardContent>
          <MacroStackedChart data={summary.days.map((day) => ({
            label: day.date.slice(5).split("-").reverse().join("/"),
            protein: day.consumed.protein_g,
            carbs: day.consumed.carbs_g,
            fat: day.consumed.fat_g,
          }))} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Adesão no período</CardTitle>
          <CardDescription>Comparação com os {days} dias anteriores ao período selecionado.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Dentro da meta kcal" value={goalDays.length ? `${Math.round((adherenceDays.length / goalDays.length) * 100)}%` : "—"} detail={`${goalDays.length ? goalDays.length - adherenceDays.length : 0} fora da faixa; ${days - goalDays.length} sem meta ignorado(s).`} />
          <Metric label="Atingimento de proteína" value={percentage(proteinAchievement)} detail={`${proteinGoalDays.length} dias com meta de proteína.`} />
          <Metric label="Média kcal" value={`${formatNumber(summary.averages.kcal)} kcal`} detail={kcalChange === null ? "Sem comparação anterior." : `${formatNumber(Math.abs(kcalChange))}% ${kcalChange >= 0 ? "acima" : "abaixo"} do período anterior.`} />
          <Metric label="Média proteína" value={`${formatNumber(summary.averages.protein_g)} g`} detail={proteinChange === null ? "Sem comparação anterior." : `${formatNumber(Math.abs(proteinChange))}% ${proteinChange >= 0 ? "acima" : "abaixo"} do período anterior.`} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Calendário de registros</CardTitle>
          <CardDescription>Selecione um dia para abrir seu acompanhamento.</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-7 gap-2">
          {summary.days.map((day) => {
            const recorded = day.entries_count > 0;
            return (
              <Link
                key={day.date}
                href={`/app?d=${day.date}`}
                title={`${dateLabel(day.date, session.user.timezone)}: ${recorded ? "com registro" : "sem registro"}`}
                aria-label={`${dateLabel(day.date, session.user.timezone)}: ${recorded ? "com registro" : "sem registro"}`}
                className={`flex aspect-square items-center justify-center rounded-md border text-xs transition-colors hover:border-primary ${recorded ? "border-primary/60 bg-primary/20 text-primary" : "text-muted-foreground"}`}
              >
                {day.date.slice(8)}
              </Link>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Principais fontes de calorias</CardTitle>
          <CardDescription>Os alimentos e descrições com mais calorias no período.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {topFoods.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Nenhum alimento registrado no período. <Link className="text-primary hover:underline" href="/app/adicionar">Registrar alimento</Link></p>
          ) : (
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead><tr className="border-b text-muted-foreground"><th className="p-3">Alimento</th><th className="p-3">Entradas</th><th className="p-3">Total</th><th className="p-3">Média</th></tr></thead>
              <tbody>{topFoods.map((food) => <tr key={`${food.food_id ?? "description"}-${food.label}`} className="border-b last:border-0"><td className="p-3 font-medium">{food.label}</td><td className="p-3">{food.entries}</td><td className="p-3">{formatNumber(food.total_kcal)} kcal</td><td className="p-3">{formatNumber(food.avg_kcal)} kcal</td></tr>)}</tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Resumo diário</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead><tr className="border-b text-muted-foreground"><th className="p-3">Dia</th><th className="p-3">Consumido</th><th className="p-3">Meta kcal</th><th className="p-3">Entradas</th></tr></thead>
            <tbody>{summary.days.map((day) => <tr key={day.date} className="border-b last:border-0"><td className="p-3"><Link className="text-primary hover:underline" href={`/app?d=${day.date}`}>{dateLabel(day.date, session.user.timezone)}</Link></td><td className="p-3">{formatNumber(day.consumed.kcal)} kcal</td><td className="p-3">{day.goal ? `${formatNumber(day.goal.kcal)} kcal` : "—"}</td><td className="p-3">{day.entries_count}</td></tr>)}</tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-lg border p-4"><p className="text-sm text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div>;
}
