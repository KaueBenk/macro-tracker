"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiSend, ApiError, UnauthorizedError } from "@/lib/api";
import type { ActionResult, UserRead } from "@/lib/types";

export async function updateTimezone(formData: FormData): Promise<ActionResult> {
  try {
    await apiSend<UserRead>("PATCH", "/api/me", {
      timezone: String(formData.get("timezone") ?? ""),
    });
    revalidatePath("/app");
    revalidatePath("/app/conta");
    return { ok: true, message: "Fuso horário atualizado." };
  } catch (error) {
    if (error instanceof UnauthorizedError) redirect("/");
    return {
      ok: false,
      message: error instanceof ApiError ? error.message : "Não foi possível atualizar a conta.",
    };
  }
}
