"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiSend, ApiError, getSession, UnauthorizedError } from "@/lib/api";
import { decimalValue, localDateTime, textValue } from "@/lib/forms";
import type { ActionResult, EntryRead } from "@/lib/types";

function failure(error: unknown): ActionResult {
  if (error instanceof UnauthorizedError) redirect("/");
  return {
    ok: false,
    message: error instanceof ApiError ? error.message : "Não foi possível salvar os dados.",
  };
}

async function sessionTimezone() {
  return (await getSession()).user.timezone;
}

export async function createFoodEntry(
  foodId: string,
  formData: FormData,
): Promise<ActionResult> {
  try {
    const timezone = await sessionTimezone();
    const date = textValue(formData, "logged_date");
    const time = textValue(formData, "logged_time");
    await apiSend<EntryRead>("POST", "/api/entries", {
      food_id: foodId,
      meal: textValue(formData, "meal") || "other",
      quantity_g: decimalValue(formData, "quantity_g", true),
      logged_at: localDateTime(date, time || undefined, timezone),
      description: textValue(formData, "description") || undefined,
    });
    revalidatePath("/app");
    revalidatePath("/app/adicionar");
    return { ok: true, message: "Entrada registrada." };
  } catch (error) {
    return failure(error);
  }
}

export async function createManualEntry(formData: FormData): Promise<ActionResult> {
  try {
    const timezone = await sessionTimezone();
    const date = textValue(formData, "logged_date");
    const time = textValue(formData, "logged_time");
    await apiSend<EntryRead>("POST", "/api/entries", {
      meal: textValue(formData, "meal") || "other",
      description: textValue(formData, "description") || undefined,
      quantity_g: decimalValue(formData, "quantity_g"),
      kcal: decimalValue(formData, "kcal", true),
      protein_g: decimalValue(formData, "protein_g", true),
      carbs_g: decimalValue(formData, "carbs_g", true),
      fat_g: decimalValue(formData, "fat_g", true),
      fiber_g: decimalValue(formData, "fiber_g"),
      logged_at: localDateTime(date, time || undefined, timezone),
    });
    revalidatePath("/app");
    revalidatePath("/app/adicionar");
    return { ok: true, message: "Entrada avulsa registrada." };
  } catch (error) {
    return failure(error);
  }
}
