"use client";

import type { FormEvent } from "react";
import { useActionState, useEffect } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/lib/types";

type DeleteAction = (formData: FormData) => Promise<ActionResult>;

export function DeleteEntryButton({ action }: { action: DeleteAction }) {
  const [state, formAction, pending] = useActionState(
    async (_previous: ActionResult | null, formData: FormData) => action(formData),
    null,
  );

  useEffect(() => {
    if (state) toast[state.ok ? "success" : "error"](state.message);
  }, [state]);

  function confirmDelete(event: FormEvent<HTMLFormElement>) {
    if (!window.confirm("Excluir esta entrada?")) {
      event.preventDefault();
    }
  }

  return (
    <form action={formAction} onSubmit={confirmDelete}>
      <Button type="submit" variant="ghost" size="icon" aria-label="Excluir entrada" disabled={pending}>
        <Trash2 className="size-4" aria-hidden="true" />
      </Button>
    </form>
  );
}
