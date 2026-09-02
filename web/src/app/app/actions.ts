"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiSend, UnauthorizedError } from "@/lib/api";
import { ApiError } from "@/lib/api";
import type { ActionResult } from "@/lib/types";

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
