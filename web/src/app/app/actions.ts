"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiGet, apiSend, ApiError, getSession, UnauthorizedError } from "@/lib/api";
import { localDateTime } from "@/lib/forms";
import type { ActionResult, EntryRead } from "@/lib/types";

export async function deleteEntry(entryId: string, formData: FormData): Promise<ActionResult> {
  void formData;
  try {
    await apiSend<void>("DELETE", `/api/entries/${entryId}`);
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      redirect("/");
    }
    return {
      ok: false,
      message: error instanceof ApiError ? error.message : "Não foi possível excluir a entrada.",
    };
  }
  revalidatePath("/app");
  return { ok: true, message: "Entrada excluída." };
}

export async function duplicateEntry(entryId: string, formData: FormData): Promise<ActionResult> {
  void formData;
  try {
    const entry = await apiGet<EntryRead>(`/api/entries/${entryId}`);
    await apiSend<EntryRead>("POST", "/api/entries", {
      logged_at: new Date().toISOString(),
      meal: entry.meal,
      food_id: entry.food_id,
      description: entry.description ?? undefined,
      quantity_g: entry.quantity_g ?? undefined,
      notes: entry.notes ?? undefined,
      kcal: entry.kcal,
      protein_g: entry.protein_g,
      carbs_g: entry.carbs_g,
      fat_g: entry.fat_g,
      fiber_g: entry.fiber_g ?? undefined,
    });
  } catch (error) {
    if (error instanceof UnauthorizedError) redirect("/");
    return {
      ok: false,
      message: error instanceof ApiError ? error.message : "Não foi possível duplicar a entrada.",
    };
  }
  revalidatePath("/app");
  return { ok: true, message: "Entrada duplicada para agora." };
}

export async function copyPreviousDay(targetDate: string, formData: FormData): Promise<ActionResult> {
  void formData;
  try {
    const session = await getSession();
    const previousDate = new Date(`${targetDate}T12:00:00Z`);
    previousDate.setUTCDate(previousDate.getUTCDate() - 1);
    const sourceDate = previousDate.toISOString().slice(0, 10);
    const entries = await apiGet<EntryRead[]>("/api/entries", { date: sourceDate });
    for (const entry of entries) {
      const localTime = new Intl.DateTimeFormat("en-US", {
        timeZone: session.user.timezone,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(entry.logged_at)).replace(/^24:/, "00:");
      await apiSend<EntryRead>("POST", "/api/entries", {
        logged_at: localDateTime(targetDate, localTime, session.user.timezone),
        meal: entry.meal,
        food_id: entry.food_id,
        description: entry.description ?? undefined,
        quantity_g: entry.quantity_g ?? undefined,
        notes: entry.notes ?? undefined,
        kcal: entry.kcal,
        protein_g: entry.protein_g,
        carbs_g: entry.carbs_g,
        fat_g: entry.fat_g,
        fiber_g: entry.fiber_g ?? undefined,
      });
    }
    revalidatePath("/app");
    return {
      ok: true,
      message: entries.length === 1 ? "1 entrada copiada." : `${entries.length} entradas copiadas.`,
    };
  } catch (error) {
    if (error instanceof UnauthorizedError) redirect("/");
    return {
      ok: false,
      message: error instanceof ApiError ? error.message : "Não foi possível copiar o dia anterior.",
    };
  }
}
