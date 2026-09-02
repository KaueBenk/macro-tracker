import Link from "next/link";

import { ActionForm } from "@/components/action-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiGet, ApiError, getSession, UnauthorizedError } from "@/lib/api";
import { formatNumber } from "@/components/progress-card";
import type { FoodRead } from "@/lib/types";

import { deleteFood, saveFood } from "./actions";

type PageProps = { searchParams: Promise<{ q?: string; edit?: string }> };

function FoodFields({ food }: { food?: FoodRead }) {
  return (
    <>
      {food && <input type="hidden" name="food_id" value={food.id} />}
      <label className="space-y-1 text-sm sm:col-span-2">
        <span>Nome</span><Input name="name" required defaultValue={food?.name} />
      </label>
      <label className="space-y-1 text-sm"><span>Marca</span><Input name="brand" defaultValue={food?.brand ?? ""} /></label>
      <label className="space-y-1 text-sm"><span>Categoria</span><Input name="category" defaultValue={food?.category ?? ""} /></label>
      {[
        ["kcal", "Calorias", food?.kcal],
        ["protein_g", "Proteína (g)", food?.protein_g],
        ["carbs_g", "Carboidrato (g)", food?.carbs_g],
        ["fat_g", "Gordura (g)", food?.fat_g],
        ["fiber_g", "Fibra (g)", food?.fiber_g],
      ].map(([name, label, value], index) => (
        <label key={name as string} className="space-y-1 text-sm">
          <span>{label as string}</span>
          <Input name={name as string} inputMode="decimal" required={index < 4} defaultValue={value == null ? "" : String(value)} />
        </label>
      ))}
    </>
  );
}

export default async function FoodsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  await getSession();
  const query = params.q?.trim() ?? "";
  let foods: FoodRead[] = [];
  let editing: FoodRead | undefined;
  let error: string | null = null;
  try {
    foods = await apiGet<FoodRead[]>("/api/foods", { search: query || undefined, limit: "100" });
    if (params.edit) editing = await apiGet<FoodRead>(`/api/foods/${params.edit}`);
  } catch (caught) {
    if (caught instanceof UnauthorizedError) throw caught;
    error = caught instanceof ApiError ? caught.message : "Não foi possível carregar alimentos.";
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <header><p className="text-sm font-medium text-primary">Biblioteca</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Alimentos</h1></header>
      <Card>
        <CardContent className="pt-6">
          <form method="get" className="flex gap-3">
            <Input name="q" defaultValue={query} placeholder="Buscar na sua biblioteca" />
            <Button type="submit">Buscar</Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{editing ? "Editar alimento" : "Criar alimento privado"}</CardTitle>
          <CardDescription>Os alimentos globais são somente leitura.</CardDescription>
        </CardHeader>
        <CardContent>
          <ActionForm action={saveFood} submitLabel={editing ? "Salvar alterações" : "Criar alimento"}>
            <div className="grid gap-4 sm:grid-cols-2"><FoodFields food={editing} /></div>
          </ActionForm>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Alimentos disponíveis</CardTitle></CardHeader>
        <CardContent className="divide-y">
          {error && <p className="py-4 text-sm text-destructive">{error}</p>}
          {!error && foods.length === 0 && <p className="py-4 text-sm text-muted-foreground">Nenhum alimento disponível.</p>}
          {foods.map((food) => (
            <article key={food.id} className="flex flex-col gap-3 py-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h3 className="font-medium">{food.name}{food.brand && <span className="ml-2 text-sm text-muted-foreground">· {food.brand}</span>}</h3>
                <p className="text-sm text-muted-foreground">{formatNumber(food.kcal)} kcal · P {formatNumber(food.protein_g)} g · C {formatNumber(food.carbs_g)} g · G {formatNumber(food.fat_g)} g</p>
                <p className="text-xs text-muted-foreground">{food.user_id ? "Alimento privado" : `Fonte externa: ${food.attribution ?? food.source ?? "não informada"}`}</p>
              </div>
              {food.user_id ? (
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" asChild><Link href={`/app/alimentos?edit=${food.id}`}>Editar</Link></Button>
                  <ActionForm action={deleteFood} submitLabel="Excluir" className="space-y-0">
                    <input type="hidden" name="food_id" value={food.id} />
                  </ActionForm>
                </div>
              ) : <span className="text-xs text-muted-foreground">Somente leitura</span>}
            </article>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
