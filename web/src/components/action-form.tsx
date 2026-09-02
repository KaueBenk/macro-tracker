"use client";

import { useActionState, useEffect, useRef } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ActionResult } from "@/lib/types";

type ServerAction = (formData: FormData) => Promise<ActionResult>;

export function ActionForm({
  action,
  children,
  className,
  confirmMessage,
  submitLabel = "Salvar",
  submitVariant = "default",
}: {
  action: ServerAction;
  children: React.ReactNode;
  className?: string;
  confirmMessage?: string;
  submitLabel?: string;
  submitVariant?: React.ComponentProps<typeof Button>["variant"];
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [state, formAction, pending] = useActionState(
    async (_previous: ActionResult | null, formData: FormData) => action(formData),
    null,
  );

  useEffect(() => {
    if (!state) return;
    toast[state.ok ? "success" : "error"](state.message);
    if (state.ok) formRef.current?.reset();
  }, [state]);

  function confirmSubmit(event: React.FormEvent<HTMLFormElement>) {
    if (confirmMessage && !window.confirm(confirmMessage)) {
      event.preventDefault();
    }
  }

  return (
    <form ref={formRef} action={formAction} onSubmit={confirmSubmit} className={cn("space-y-4", className)}>
      {children}
      <Button type="submit" variant={submitVariant} disabled={pending}>
        {pending ? "Salvando…" : submitLabel}
      </Button>
    </form>
  );
}
