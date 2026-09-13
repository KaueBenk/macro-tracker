export function decimalValue(formData: FormData, name: string, required = false) {
  const raw = String(formData.get(name) ?? "").trim().replace(",", ".");
  if (!raw) {
    if (required) throw new Error("Preencha todos os campos obrigatórios.");
    return undefined;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error("Use números maiores ou iguais a zero.");
  }
  return value;
}

export function textValue(formData: FormData, name: string) {
  return String(formData.get(name) ?? "").trim();
}

export function localDateTime(
  date: string,
  time: string | undefined,
  timezone: string,
) {
  const clock = time || "12:00";
  const probe = new Date(`${date}T${clock}:00Z`);
  const offsetPart = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    timeZoneName: "longOffset",
  })
    .formatToParts(probe)
    .find((part) => part.type === "timeZoneName")?.value;
  const offset = offsetPart === "GMT" ? "Z" : (offsetPart ?? "GMT").replace("GMT", "");
  return new Date(`${date}T${clock}:00${offset}`).toISOString();
}
