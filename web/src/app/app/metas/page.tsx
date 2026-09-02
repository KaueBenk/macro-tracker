import { ActionForm } from "@/components/action-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiGet, getSession } from "@/lib/api";
import { formatNumber } from "@/components/progress-card";
import type { GoalRead } from "@/lib/types";

import { saveGoal } from "./actions";

export default async function GoalsPage() {
  const session = await getSession();
  const goals = await apiGet<GoalRead[]>("/api/goals");
  const current = goals[0];
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: session.user.timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <header><p className="text-sm font-medium text-primary">Planejamento</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Metas diárias</h1></header>
      <Card>
        <CardHeader><CardTitle>{current ? "Meta atual e próxima meta" : "Definir meta diária"}</CardTitle><CardDescription>Os valores são aplicados a partir da data informada.</CardDescription></CardHeader>
        <CardContent>
          <ActionForm action={saveGoal} submitLabel="Salvar meta">
            <div className="grid gap-4 sm:grid-cols-2">
              {[
                ["kcal", "Calorias", current?.kcal],
                ["protein_g", "Proteína (g)", current?.protein_g],
                ["carbs_g", "Carboidrato (g)", current?.carbs_g],
                ["fat_g", "Gordura (g)", current?.fat_g],
                ["fiber_g", "Fibra (g)", current?.fiber_g],
              ].map(([name, label, value], index) => (
                <label key={name as string} className="space-y-1 text-sm">
                  <span>{label as string}</span>
                  <Input name={name as string} inputMode="decimal" required={index < 4} defaultValue={value == null ? "" : String(value)} />
                </label>
              ))}
              <label className="space-y-1 text-sm"><span>Vigente a partir de</span><Input type="date" name="effective_from" defaultValue={today} required /></label>
            </div>
          </ActionForm>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Histórico de metas</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <thead><tr className="border-b text-muted-foreground"><th className="p-3">Data</th><th className="p-3">Kcal</th><th className="p-3">Proteína</th><th className="p-3">Carboidrato</th><th className="p-3">Gordura</th><th className="p-3">Fibra</th></tr></thead>
            <tbody>
              {goals.map((goal) => <tr key={goal.id} className="border-b last:border-0"><td className="p-3">{new Intl.DateTimeFormat("pt-BR").format(new Date(`${goal.effective_from}T12:00:00Z`))}</td><td className="p-3">{formatNumber(goal.kcal)} kcal</td><td className="p-3">{formatNumber(goal.protein_g)} g</td><td className="p-3">{formatNumber(goal.carbs_g)} g</td><td className="p-3">{formatNumber(goal.fat_g)} g</td><td className="p-3">{formatNumber(goal.fiber_g ?? 0)} g</td></tr>)}
              {goals.length === 0 && <tr><td colSpan={6} className="p-4 text-muted-foreground">Nenhuma meta cadastrada.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
