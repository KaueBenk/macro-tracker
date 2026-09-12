"use client";

import { Copy } from "lucide-react";
import { useActionState, useEffect } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/lib/types";

type DuplicateAction = (formData: FormData) => Promise<ActionResult>;

export function DuplicateEntryButton({ action }: { action: DuplicateAction }) {
  const [state, formAction, pending] = useActionState(
    async (_previous: ActionResult | null, formData: FormData) => action(formData),
    null,
  );

  useEffect(() => {
    if (state) toast[state.ok ? "success" : "error"](state.message);
  }, [state]);

  return (
    <form action={formAction}>
      <Button type="submit" variant="ghost" size="icon" aria-label="Duplicar entrada" disabled={pending}>
        <Copy className="size-4" aria-hidden="true" />
      </Button>
    </form>
  );
}
