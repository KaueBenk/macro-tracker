export type Meal = "breakfast" | "lunch" | "dinner" | "snack" | "other";

export interface UserRead {
  id: string;
  email: string;
  timezone: string;
}

export interface SessionRead {
  user: UserRead;
  csrf_token: string | null;
}

export interface FoodRead {
  id: string;
  user_id: string | null;
  name: string;
  brand: string | null;
  category: string | null;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number | null;
  serving_label: string | null;
  serving_grams: number | null;
  source: string | null;
  source_ref: string | null;
  source_version: string | null;
  attribution: string | null;
  barcode: string | null;
  locale: string | null;
  nutrients: Record<string, number> | null;
  created_at: string;
  updated_at: string;
}

export interface EntryRead {
  id: string;
  user_id: string;
  logged_at: string;
  meal: Meal;
  food_id: string | null;
  description: string | null;
  quantity_g: number | null;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalRead {
  id: string;
  user_id: string;
  effective_from: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number | null;
  created_at: string;
  updated_at: string;
}

export interface Totals {
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
}

export interface Progress {
  consumed: Totals;
  goal: Totals | null;
  remaining: Totals | null;
  percent: Totals;
}

export interface DailySummary extends Progress {
  date: string;
  entries_count: number;
  by_meal: Record<Meal, Totals>;
}

export interface RangeSummary {
  days: DailySummary[];
  averages: Totals;
}

export interface ActionResult {
  ok: boolean;
  message: string;
}
