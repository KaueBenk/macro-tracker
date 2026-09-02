import { Search } from "lucide-react";

import { ActionForm } from "@/components/action-form";
import { FoodEntryForm } from "@/components/food-entry-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MealSelect } from "@/components/meal-select";
import { RemoteSearchToggle } from "@/components/remote-search-toggle";
import { formatNumber } from "@/components/progress-card";
import { apiGet, ApiError, getSession, UnauthorizedError } from "@/lib/api";
import type { FoodRead } from "@/lib/types";

import { createFoodEntry, createManualEntry } from "./actions";

type PageProps = {
  searchParams: Promise<{ q?: string; remote?: string; barcode?: string }>;
};

function todayInTimezone(timezone: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function FoodResult({ food, date }: { food: FoodRead; date: string }) {
  return (
    <article className="border-t py-5 first:border-t-0">
      <div className="flex flex-col gap-1">
        <h3 className="font-medium">
          {food.name}
          {food.brand && <span className="ml-2 text-sm text-muted-foreground">{food.brand}</span>}
        </h3>
        <p className="text-sm text-muted-foreground">
          {formatNumber(food.kcal)} kcal · P {formatNumber(food.protein_g)} g · C{" "}
          {formatNumber(food.carbs_g)} g · G {formatNumber(food.fat_g)} g · F{" "}
          {formatNumber(food.fiber_g ?? 0)} g por 100 g
        </p>
        <p className="text-xs text-muted-foreground">
          {food.user_id ? "Alimento privado" : `Fonte: ${food.attribution ?? food.source ?? "externa"}`}
        </p>
      </div>
      <FoodEntryForm food={food} action={createFoodEntry.bind(null, food.id)} date={date} />
    </article>
  );
}

export default async function AddPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const session = await getSession();
  const date = todayInTimezone(session.user.timezone);
  const query = params.q?.trim() ?? "";
  const barcode = params.barcode?.trim() ?? "";
  const remote = params.remote === "true";
  let foods: FoodRead[] = [];
  let searchError: string | null = null;

  if (query) {
    try {
      foods = await apiGet<FoodRead[]>("/api/foods", {
        search: query,
        remote: remote ? "true" : undefined,
      });
    } catch (error) {
      if (error instanceof UnauthorizedError) throw error;
      searchError = error instanceof ApiError ? error.message : "Não foi possível buscar alimentos.";
    }
  }
  if (barcode) {
    try {
      const food = await apiGet<FoodRead>(`/api/foods/barcode/${encodeURIComponent(barcode)}`);
      foods = [food, ...foods.filter((item) => item.id !== food.id)];
    } catch (error) {
      if (error instanceof UnauthorizedError) throw error;
      searchError = error instanceof ApiError ? error.message : "Código de barras não encontrado.";
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <p className="text-sm font-medium text-primary">Registro</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Adicionar alimento</h1>
      </header>
      <Card>
        <CardHeader>
          <CardTitle>Buscar por texto</CardTitle>
          <CardDescription>A busca externa é opcional e só acontece ao enviar o formulário.</CardDescription>
        </CardHeader>
        <CardContent>
          <form method="get" className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <Label className="sr-only" htmlFor="food-query">Alimento</Label>
            <Input id="food-query" name="q" defaultValue={query} placeholder="Ex.: arroz integral" />
            <div className="flex items-center gap-3 sm:col-span-2">
              <label className="flex items-center gap-2 text-sm" htmlFor="remote-search">
                <RemoteSearchToggle defaultChecked={remote} />
                Buscar em fontes externas
              </label>
              <Button type="submit"><Search className="mr-2 size-4" aria-hidden="true" />Buscar</Button>
            </div>
          </form>
          {searchError && <p className="mt-4 text-sm text-destructive">{searchError}</p>}
          {(query || barcode) && !searchError && foods.length === 0 && (
            <p className="mt-5 text-sm text-muted-foreground">Nenhum alimento encontrado.</p>
          )}
          {(query || barcode) && foods.length > 0 && (
            <div className="mt-5">{foods.map((food) => <FoodResult key={food.id} food={food} date={date} />)}</div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Buscar por código de barras</CardTitle></CardHeader>
        <CardContent>
          <form method="get" className="flex gap-3">
            <Input name="barcode" defaultValue={barcode} inputMode="numeric" placeholder="Somente números" />
            <Button type="submit">Buscar</Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Entrada avulsa</CardTitle>
          <CardDescription>Registre macros informados manualmente.</CardDescription>
        </CardHeader>
        <CardContent>
          <ActionForm action={createManualEntry}>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1 text-sm sm:col-span-2">
                <span>Descrição</span><Input name="description" required />
              </label>
              {[
                ["kcal", "Calorias", true],
                ["protein_g", "Proteína (g)", true],
                ["carbs_g", "Carboidrato (g)", true],
                ["fat_g", "Gordura (g)", true],
                ["fiber_g", "Fibra (g)", false],
                ["quantity_g", "Gramas", false],
              ].map(([name, label, required]) => (
                <label key={name as string} className="space-y-1 text-sm">
                  <span>{label as string}</span>
                  <Input name={name as string} inputMode="decimal" required={required as boolean} />
                </label>
              ))}
              <label className="space-y-1 text-sm">
                <span>Refeição</span>
                <MealSelect />
              </label>
              <label className="space-y-1 text-sm"><span>Data</span><Input type="date" name="logged_date" defaultValue={date} required /></label>
              <label className="space-y-1 text-sm"><span>Hora (opcional)</span><Input type="time" name="logged_time" /></label>
            </div>
          </ActionForm>
        </CardContent>
      </Card>
    </div>
  );
}
