"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiSend, UnauthorizedError } from "@/lib/api";

export async function deleteEntry(entryId: string, formData: FormData) {
  void formData;
  try {
    await apiSend<void>("DELETE", `/api/entries/${entryId}`);
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      redirect("/");
    }
    throw error;
  }
  revalidatePath("/app");
}
