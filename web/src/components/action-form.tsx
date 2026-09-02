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
  submitLabel = "Salvar",
}: {
  action: ServerAction;
  children: React.ReactNode;
  className?: string;
  submitLabel?: string;
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

  return (
    <form ref={formRef} action={formAction} className={cn("space-y-4", className)}>
      {children}
      <Button type="submit" disabled={pending}>
        {pending ? "Salvando…" : submitLabel}
      </Button>
    </form>
  );
}
