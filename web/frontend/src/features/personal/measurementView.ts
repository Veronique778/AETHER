import type { Measurement, MeasurementQuery } from '../../api/accountApi';

export type PersonalChartSeries = {
  unit: string;
  origins: string[];
  qualities: string[];
  points: { x: number; y: number | null }[];
};

const INVALID_QUALITIES = new Set(['rejected', 'corrupt', 'no_contact', 'connection_lost']);

export function personalMeasurementQuery(start: string, end: string): MeasurementQuery {
  return {
    ...(start ? { start: `${start}T00:00:00.000000Z` } : {}),
    ...(end ? { end: `${end}T23:59:59.999999Z` } : {}),
    limit: 100,
  };
}

export function chartSeriesForSignal(items: Measurement[], signal: string): PersonalChartSeries[] {
  const grouped = new Map<string, Measurement[]>();
  for (const item of items) {
    if (item.signal !== signal || item.measured_at === null) continue;
    const timestamp = Date.parse(item.measured_at);
    if (!Number.isFinite(timestamp)) continue;
    const group = grouped.get(item.unit) ?? [];
    group.push(item);
    grouped.set(item.unit, group);
  }

  return [...grouped.entries()].map(([unit, measurements]) => ({
    unit,
    origins: [...new Set(measurements.map((item) => item.origin))].sort(),
    qualities: [...new Set(measurements.map((item) => item.quality))].sort(),
    points: measurements
      .sort((a, b) => Date.parse(a.measured_at!) - Date.parse(b.measured_at!))
      .map((item) => ({
        x: Date.parse(item.measured_at!),
        y: item.value === null || item.missing || INVALID_QUALITIES.has(item.quality) ? null : item.value,
      })),
  }));
}

export function latestValidMeasurement(items: Measurement[], signal: string): Measurement | null {
  return items
    .filter((item) => item.signal === signal
      && item.measured_at !== null
      && item.value !== null
      && !item.missing
      && !INVALID_QUALITIES.has(item.quality)
      && Number.isFinite(Date.parse(item.measured_at)))
    .reduce<Measurement | null>((latest, item) => (
      latest === null || Date.parse(item.measured_at!) > Date.parse(latest.measured_at!)
        ? item
        : latest
    ), null);
}
