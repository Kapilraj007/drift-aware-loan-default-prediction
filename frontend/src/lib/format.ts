export const formatCurrency = (value: number | null | undefined): string =>
  value === null || value === undefined
    ? "—"
    : new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);

export const formatPercent = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(value);
};

export const formatDate = (value: string | null | undefined): string =>
  value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";

export const titleCase = (value: string): string =>
  value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
