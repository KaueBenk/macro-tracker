"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiSend, ApiError, UnauthorizedError } from "@/lib/api";
import { decimalValue, textValue } from "@/lib/forms";
import type { ActionResult, FoodRead } from "@/lib/types";

function payload(formData: FormData) {
  return {
    name: textValue(formData, "name"),
    brand: textValue(formData, "brand") || undefined,
    category: textValue(formData, "category") || undefined,
    kcal: decimalValue(formData, "kcal", true),
    protein_g: decimalValue(formData, "protein_g", true),
    carbs_g: decimalValue(formData, "carbs_g", true),
    fat_g: decimalValue(formData, "fat_g", true),
    fiber_g: decimalValue(formData, "fiber_g"),
  };
}

function failure(error: unknown): ActionResult {
  if (error instanceof UnauthorizedError) redirect("/");
  return {
    ok: false,
    message: error instanceof ApiError ? error.message : "Não foi possível salvar o alimento.",
  };
}

export async function saveFood(formData: FormData): Promise<ActionResult> {
  try {
    const foodId = textValue(formData, "food_id");
    const result = await apiSend<FoodRead>(
      foodId ? "PATCH" : "POST",
      foodId ? `/api/foods/${foodId}` : "/api/foods",
      payload(formData),
    );
    void result;
    revalidatePath("/app/alimentos");
    return { ok: true, message: foodId ? "Alimento atualizado." : "Alimento criado." };
  } catch (error) {
    return failure(error);
  }
}

export async function deleteFood(formData: FormData): Promise<ActionResult> {
  try {
    await apiSend<void>("DELETE", `/api/foods/${textValue(formData, "food_id")}`);
    revalidatePath("/app/alimentos");
    return { ok: true, message: "Alimento excluído." };
  } catch (error) {
    return failure(error);
  }
}
