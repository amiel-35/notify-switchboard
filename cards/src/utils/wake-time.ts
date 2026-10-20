const TIME_OF_DAY_RE = /^([01]?\d|2[0-3]):([0-5]\d)$/;

const formatterCache = new Map<string, Intl.DateTimeFormat>();

function getFormatter(timeZone: string | undefined): Intl.DateTimeFormat {
  const key = timeZone ?? "";
  let formatter = formatterCache.get(key);
  if (!formatter) {
    const options: Intl.DateTimeFormatOptions = {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    };
    try {
      formatter = new Intl.DateTimeFormat("en-US", timeZone ? { ...options, timeZone } : options);
    } catch {
      // An unknown IANA zone throws a RangeError; fall back to the browser's.
      formatter = new Intl.DateTimeFormat("en-US", options);
    }
    formatterCache.set(key, formatter);
  }
  return formatter;
}

/** Seconds elapsed since midnight, as read on a wall clock in `timeZone`. */
function secondsSinceMidnight(now: Date, timeZone: string | undefined): number {
  const parts = getFormatter(timeZone).formatToParts(now);
  let hours = 0;
  let minutes = 0;
  let seconds = 0;
  for (const part of parts) {
    if (part.type === "hour") hours = Number(part.value) % 24;
    else if (part.type === "minute") minutes = Number(part.value);
    else if (part.type === "second") seconds = Number(part.value);
  }
  return hours * 3600 + minutes * 60 + seconds;
}

/**
 * Computes the number of whole minutes from `now` until the next
 * occurrence of `wakeTime` (a "HH:MM" 24h string) **as read on the Home
 * Assistant instance's own clock** (`hass.config.time_zone`), not the
 * browser's. A phone left on holiday time would otherwise silence the
 * router for the wrong number of hours.
 *
 * If that time has already passed today, the result rolls over to
 * tomorrow. Returns `null` when `wakeTime` is not a valid "HH:MM" string.
 *
 * The rollover is computed on wall-clock seconds, so a DST transition
 * between now and the wake time shifts the result by an hour; that is
 * acceptable for a "silence me until morning" control and avoids pulling
 * in a full timezone library.
 */
export function minutesUntilWakeTime(
  wakeTime: string,
  now: Date = new Date(),
  timeZone?: string,
): number | null {
  const match = TIME_OF_DAY_RE.exec(wakeTime.trim());
  if (!match) {
    return null;
  }
  const targetSeconds = Number(match[1]) * 3600 + Number(match[2]) * 60;
  const nowSeconds = secondsSinceMidnight(now, timeZone);

  let delta = targetSeconds - nowSeconds;
  if (delta <= 0) {
    delta += 86400;
  }
  return Math.max(1, Math.round(delta / 60));
}
