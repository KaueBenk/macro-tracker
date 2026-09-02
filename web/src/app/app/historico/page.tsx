import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiGet, getSession } from "@/lib/api";
import { formatNumber } from "@/components/progress-card";
import type { RangeSummary } from "@/lib/types";

type PageProps = { searchParams: Promise<{ days?: string }> };

export default async function HistoryPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const days = params.days === "30" ? 30 : 7;
  const session = await getSession();
  const end = new Intl.DateTimeFormat("en-CA", {
    timeZone: session.user.timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const startDate = new Date(`${end}T12:00:00Z`);
  startDate.setUTCDate(startDate.getUTCDate() - days + 1);
  const start = startDate.toISOString().slice(0, 10);
  const summary = await apiGet<RangeSummary>("/api/summary/range", { from: start, to: end });
  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm font-medium text-primary">Tendências</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Histórico</h1></div><div className="flex gap-2"><Button variant={days === 7 ? "default" : "outline"} asChild><Link href="/app/historico?days=7">7 dias</Link></Button><Button variant={days === 30 ? "default" : "outline"} asChild><Link href="/app/historico?days=30">30 dias</Link></Button></div></header>
      <Card>
        <CardHeader><CardTitle>Médias dos {days} dias</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-5">
          <span>{formatNumber(summary.averages.kcal)} kcal</span><span>P {formatNumber(summary.averages.protein_g)} g</span><span>C {formatNumber(summary.averages.carbs_g)} g</span><span>G {formatNumber(summary.averages.fat_g)} g</span><span>F {formatNumber(summary.averages.fiber_g)} g</span>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Resumo diário</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm"><thead><tr className="border-b text-muted-foreground"><th className="p-3">Dia</th><th className="p-3">Consumido</th><th className="p-3">Meta kcal</th><th className="p-3">Entradas</th></tr></thead><tbody>
            {summary.days.map((day) => <tr key={day.date} className="border-b last:border-0"><td className="p-3"><Link className="text-primary hover:underline" href={`/app?d=${day.date}`}>{new Intl.DateTimeFormat("pt-BR", { timeZone: session.user.timezone }).format(new Date(`${day.date}T12:00:00Z`))}</Link></td><td className="p-3">{formatNumber(day.consumed.kcal)} kcal</td><td className="p-3">{day.goal ? `${formatNumber(day.goal.kcal)} kcal` : "—"}</td><td className="p-3">{day.entries_count}</td></tr>)}
          </tbody></table>
        </CardContent>
      </Card>
    </div>
  );
}
