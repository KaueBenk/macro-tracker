import Link from "next/link";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";

import { DatePicker } from "@/components/date-picker";
import { DeleteEntryButton } from "@/components/delete-entry-button";
import { ProgressCard, formatNumber, totalsForProgress } from "@/components/progress-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { apiGet, getSession } from "@/lib/api";
import type { DailySummary, EntryRead, FoodRead, Meal } from "@/lib/types";

import { deleteEntry } from "@/app/app/actions";

const mealLabels: Record<Meal, string> = {
  breakfast: "Café da manhã",
  lunch: "Almoço",
  dinner: "Jantar",
  snack: "Lanche",
  other: "Outro",
};

const mealOrder: Meal[] = ["breakfast", "lunch", "dinner", "snack", "other"];

function todayInTimezone(timezone: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function validDate(value: string | undefined, timezone: string) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return todayInTimezone(timezone);
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? todayInTimezone(timezone) : value;
}

function shiftDate(value: string, days: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function displayDate(value: string) {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "full",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

function displayTime(value: string, timezone: string) {
  return new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(value));
}

function EntryRow({
  entry,
  food,
  timezone,
}: {
  entry: EntryRead;
  food: FoodRead | undefined;
  timezone: string;
}) {
  const title = food?.name ?? entry.description ?? "Entrada avulsa";
  return (
    <div className="flex items-start justify-between gap-3 py-4">
      <div className="min-w-0 space-y-1">
        <h4 className="font-medium">{title}</h4>
        {food && entry.description && (
          <p className="text-sm text-muted-foreground">{entry.description}</p>
        )}
        <p className="text-xs text-muted-foreground">
          {displayTime(entry.logged_at, timezone)} ·{" "}
          {entry.quantity_g === null ? "—" : `${formatNumber(entry.quantity_g)} g`}
        </p>
        {food?.attribution && (
          <p className="text-xs text-muted-foreground">Fonte: {food.attribution}</p>
        )}
        <p className="text-sm tabular-nums text-muted-foreground">
          {formatNumber(entry.kcal)} kcal · P {formatNumber(entry.protein_g)} g · C{" "}
          {formatNumber(entry.carbs_g)} g · G {formatNumber(entry.fat_g)} g · F{" "}
          {formatNumber(entry.fiber_g ?? 0)} g
        </p>
      </div>
      <DeleteEntryButton action={deleteEntry.bind(null, entry.id)} />
    </div>
  );
}

type PageProps = {
  searchParams: Promise<{ d?: string | string[] }>;
};

export default async function TodayPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const session = await getSession();
  const requestedDate = Array.isArray(params.d) ? params.d[0] : params.d;
  const day = validDate(requestedDate, session.user.timezone);
  const [summary, entries] = await Promise.all([
    apiGet<DailySummary>("/api/summary/daily", { date: day }),
    apiGet<EntryRead[]>("/api/entries", { date: day }),
  ]);

  const foodIds = [
    ...new Set(entries.flatMap((entry) => (entry.food_id ? [entry.food_id] : []))),
  ];
  const foodPairs = await Promise.all(
    foodIds.map(async (foodId) => {
      try {
        return [foodId, await apiGet<FoodRead>(`/api/foods/${foodId}`)] as const;
      } catch {
        return null;
      }
    }),
  );
  const foods = new Map(
    foodPairs.filter((pair): pair is readonly [string, FoodRead] => pair !== null),
  );

  const progress = totalsForProgress(summary.consumed);
  const goal = summary.goal;
  const remaining = summary.remaining;
  const percent = summary.percent;
  const grouped = new Map<Meal, EntryRead[]>();
  for (const entry of entries) {
    grouped.set(entry.meal, [...(grouped.get(entry.meal) ?? []), entry]);
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
      <header className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-primary">Seu dia</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight capitalize">
            {displayDate(day)}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Fuso horário: {session.user.timezone}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" asChild aria-label="Dia anterior">
            <Link href={`/app?d=${shiftDate(day, -1)}`}>
              <ChevronLeft className="size-4" aria-hidden="true" />
            </Link>
          </Button>
          <DatePicker value={day} />
          <Button variant="outline" size="icon" asChild aria-label="Próximo dia">
            <Link href={`/app?d=${shiftDate(day, 1)}`}>
              <ChevronRight className="size-4" aria-hidden="true" />
            </Link>
          </Button>
          <Button variant="secondary" asChild className="hidden sm:inline-flex">
            <Link href={`/app?d=${todayInTimezone(session.user.timezone)}`}>Hoje</Link>
          </Button>
        </div>
      </header>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5" aria-label="Progresso do dia">
        {progress.map((metric) => (
          <ProgressCard
            key={metric.key}
            label={metric.label}
            unit={metric.unit}
            consumed={metric.value}
            goal={goal?.[metric.key] ?? null}
            remaining={remaining?.[metric.key] ?? null}
            percent={percent[metric.key]}
          />
        ))}
      </section>

      {!summary.goal && (
        <Card className="mt-6 border-dashed">
          <CardContent className="flex flex-col gap-3 py-5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">Você ainda não definiu uma meta diária.</p>
            <Button variant="outline" asChild>
              <Link href="/app/metas">Definir metas</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      <Card className="mt-6">
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Entradas</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              {summary.entries_count}{" "}
              {summary.entries_count === 1 ? "registro" : "registros"} no dia
            </p>
          </div>
          <Button asChild>
            <Link href="/app/adicionar">
              <Plus className="mr-2 size-4" aria-hidden="true" />
              Registrar
            </Link>
          </Button>
        </CardHeader>
        <CardContent>
          {entries.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Nenhuma entrada registrada neste dia.
            </p>
          ) : (
            <div>
              {mealOrder.map((meal) => {
                const mealEntries = grouped.get(meal);
                if (!mealEntries?.length) return null;
                return (
                  <section key={meal} aria-labelledby={`meal-${meal}`}>
                    <h3 id={`meal-${meal}`} className="pt-3 text-sm font-semibold text-primary">
                      {mealLabels[meal]}
                    </h3>
                    <div className="divide-y">
                      {mealEntries.map((entry) => (
                        <EntryRow
                          key={entry.id}
                          entry={entry}
                          food={entry.food_id ? foods.get(entry.food_id) : undefined}
                          timezone={session.user.timezone}
                        />
                      ))}
                    </div>
                    <Separator />
                  </section>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
