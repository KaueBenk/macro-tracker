"use client";

import type { FormEvent } from "react";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";

type DeleteAction = (formData: FormData) => Promise<void>;

export function DeleteEntryButton({ action }: { action: DeleteAction }) {
  function confirmDelete(event: FormEvent<HTMLFormElement>) {
    if (!window.confirm("Excluir esta entrada?")) {
      event.preventDefault();
    }
  }

  return (
    <form action={action} onSubmit={confirmDelete}>
      <Button type="submit" variant="ghost" size="icon" aria-label="Excluir entrada">
        <Trash2 className="size-4" aria-hidden="true" />
      </Button>
    </form>
  );
}
