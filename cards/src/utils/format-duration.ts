const UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

const formatterCache = new Map<string, Intl.RelativeTimeFormat>();

function getFormatter(language: string): Intl.RelativeTimeFormat {
  let formatter = formatterCache.get(language);
  if (!formatter) {
    try {
      formatter = new Intl.RelativeTimeFormat(language, { numeric: "always", style: "long" });
    } catch {
      formatter = new Intl.RelativeTimeFormat("en", { numeric: "always", style: "long" });
    }
    formatterCache.set(language, formatter);
  }
  return formatter;
}

/**
 * Formats the time elapsed since `since` (an ISO-8601 timestamp, e.g. a
 * `last_changed`) as a localized relative string such as "5 minutes ago" /
 * "il y a 5 minutes" / "hace 5 minutos", using the platform's
 * `Intl.RelativeTimeFormat` so plural rules and grammar stay correct for
 * every locale without us hand-rolling them.
 */
export function formatRelativeDuration(
  since: string,
  language: string,
  now: Date = new Date(),
): string {
  const fromMs = new Date(since).getTime();
  if (Number.isNaN(fromMs)) {
    return "";
  }
  const diffSeconds = Math.round((now.getTime() - fromMs) / 1000);
  const formatter = getFormatter(language);

  for (const [unit, secondsInUnit] of UNITS) {
    const absSeconds = Math.abs(diffSeconds);
    if (absSeconds >= secondsInUnit || unit === "second") {
      const value = Math.round(diffSeconds / secondsInUnit);
      return formatter.format(-value, unit);
    }
  }
  return formatter.format(0, "second");
}
