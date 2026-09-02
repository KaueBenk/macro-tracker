"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiSend, ApiError, UnauthorizedError } from "@/lib/api";
import { decimalValue, textValue } from "@/lib/forms";
import type { ActionResult, GoalRead } from "@/lib/types";

export async function saveGoal(formData: FormData): Promise<ActionResult> {
  try {
    await apiSend<GoalRead>("PUT", "/api/goals", {
      effective_from: textValue(formData, "effective_from") || undefined,
      kcal: decimalValue(formData, "kcal", true),
      protein_g: decimalValue(formData, "protein_g", true),
      carbs_g: decimalValue(formData, "carbs_g", true),
      fat_g: decimalValue(formData, "fat_g", true),
      fiber_g: decimalValue(formData, "fiber_g"),
    });
    revalidatePath("/app");
    revalidatePath("/app/metas");
    return { ok: true, message: "Meta salva." };
  } catch (error) {
    if (error instanceof UnauthorizedError) redirect("/");
    return {
      ok: false,
      message: error instanceof ApiError ? error.message : "Não foi possível salvar a meta.",
    };
  }
}
