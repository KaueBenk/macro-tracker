"use client";

import { useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";

export function RemoteSearchToggle({ defaultChecked = false }: { defaultChecked?: boolean }) {
  const [checked, setChecked] = useState(defaultChecked);
  return (
    <>
      <Checkbox
        id="remote-search"
        checked={checked}
        onCheckedChange={(value) => setChecked(value === true)}
      />
      <input type="hidden" name="remote" value="true" disabled={!checked} />
    </>
  );
}
