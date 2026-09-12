export function dateInTimezone(timezone: string, value = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(value);
}

export function shiftDate(value: string, days: number) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function dateLabel(value: string, timezone = "UTC") {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "medium",
    timeZone: timezone,
  }).format(new Date(`${value}T12:00:00Z`));
}
