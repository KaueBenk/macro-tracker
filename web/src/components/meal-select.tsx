"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const meals = [
  ["breakfast", "Café da manhã"],
  ["lunch", "Almoço"],
  ["dinner", "Jantar"],
  ["snack", "Lanche"],
  ["other", "Outro"],
] as const;

export function MealSelect({ defaultValue = "other" }: { defaultValue?: string }) {
  return (
    <Select name="meal" defaultValue={defaultValue}>
      <SelectTrigger className="w-full">
        <SelectValue placeholder="Selecione a refeição" />
      </SelectTrigger>
      <SelectContent>
        {meals.map(([value, label]) => (
          <SelectItem key={value} value={value}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
