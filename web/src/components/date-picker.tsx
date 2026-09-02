"use client";

import { format, parseISO } from "date-fns";
import { CalendarDays } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export function DatePicker({ value }: { value: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const selected = parseISO(value);

  function chooseDate(date: Date | undefined) {
    if (!date) return;
    router.push(`/app?d=${format(date, "yyyy-MM-dd")}`);
    setOpen(false);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn("min-w-0 flex-1 justify-between font-normal", !value && "text-muted-foreground")}
          aria-label="Escolher data"
        >
          <span>{format(selected, "dd/MM/yyyy")}</span>
          <CalendarDays className="size-4 shrink-0 opacity-70" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="center">
        <Calendar
          mode="single"
          selected={selected}
          onSelect={chooseDate}
          defaultMonth={selected}
        />
      </PopoverContent>
    </Popover>
  );
}
