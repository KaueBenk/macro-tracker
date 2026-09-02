import { ActionForm } from "@/components/action-form";
import { Input } from "@/components/ui/input";
import { MealSelect } from "@/components/meal-select";
import type { ActionResult, FoodRead } from "@/lib/types";

type FoodAction = (formData: FormData) => Promise<ActionResult>;

export function FoodEntryForm({
  food,
  action,
  date,
}: {
  food: FoodRead;
  action: FoodAction;
  date: string;
}) {
  return (
    <ActionForm action={action} className="mt-4 border-t pt-4">
      <input type="hidden" name="food_id" value={food.id} />
      <div className="grid gap-3 sm:grid-cols-4">
        <label className="space-y-1 text-sm">
          <span>Gramas</span>
          <Input name="quantity_g" inputMode="decimal" placeholder="100" required />
        </label>
        <label className="space-y-1 text-sm">
          <span>Refeição</span>
          <MealSelect />
        </label>
        <label className="space-y-1 text-sm">
          <span>Data</span>
          <Input type="date" name="logged_date" defaultValue={date} required />
        </label>
        <label className="space-y-1 text-sm">
          <span>Hora (opcional)</span>
          <Input type="time" name="logged_time" />
        </label>
      </div>
      <label className="block space-y-1 text-sm">
        <span>Descrição opcional</span>
        <Input name="description" placeholder="Ex.: com leite" />
      </label>
    </ActionForm>
  );
}
