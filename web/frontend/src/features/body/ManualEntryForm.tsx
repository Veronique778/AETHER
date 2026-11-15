import { useState, type FormEvent } from 'react';
import { METRIC_KEYS, type MeasurementInput, type MetricKey } from '../../api/types';
import { METRICS } from '../../lib/format';
import { MAX_DAY, useApp } from '../../state/AppState';
import { Button, Card, Notice, NumberField } from '../../ui';

/** Validation limits – identical to the backend pydantic model (schemas.Measurement). */
export const LIMITS: Record<MetricKey, [number, number]> = {
  heart_rate_bpm: [20, 240], sleep_hours: [0, 24], fatigue_1_10: [1, 10], reaction_ms: [50, 2000], activity_minutes: [0, 1440],
};

export function validateMeasurement(day: string, values: Record<MetricKey, string>): { errors: Partial<Record<MetricKey | 'day' | 'form', string>>; payload?: MeasurementInput } {
  const errors: Partial<Record<MetricKey | 'day' | 'form', string>> = {};
  const d = Number(day);
  if (!Number.isInteger(d) || d < 1 || d > 9999) errors.day = 'Mission day must be a whole number ≥ 1.';
  const payload: MeasurementInput = { day: d };
  let any = false;
  for (const k of METRIC_KEYS) {
    const raw = values[k].trim();
    if (!raw) continue;
    const v = Number(raw);
    const [lo, hi] = LIMITS[k];
    if (!Number.isFinite(v)) errors[k] = 'Enter a number.';
    else if (v < lo || v > hi) errors[k] = `Must be between ${lo} and ${hi} ${METRICS[k].unit}.`;
    else { payload[k] = v; any = true; }
  }
  if (!any && !Object.keys(errors).length) errors.form = 'Enter at least one measurement.';
  return Object.keys(errors).length ? { errors } : { errors, payload };
}

const EMPTY = Object.fromEntries(METRIC_KEYS.map((k) => [k, ''])) as Record<MetricKey, string>;

/** Manual entry. `bare` renders without a card (used inside the BODY quick-entry dialog). */
export function ManualEntryForm({ bare = false, initialDay, initialMetric, onSaved }: { bare?: boolean; initialDay?: number; initialMetric?: MetricKey; onSaved?: (day: number) => void } = {}) {
  const { api, astronautId, bumpData, day: missionDay } = useApp();
  const [day, setDay] = useState(String(initialDay ?? missionDay));
  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<MetricKey | 'day' | 'form', string>>>({});
  const [status, setStatus] = useState<{ tone: 'good' | 'high'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setStatus(null);
    const res = validateMeasurement(day, values);
    setErrors(res.errors);
    if (!res.payload) return;
    setBusy(true);
    try {
      await api.saveMeasurement(astronautId, res.payload);
      setStatus({ tone: 'good', text: `Saved for day ${res.payload.day}. Values not entered keep their previous record. Charts and PHANTOM have been refreshed.` });
      setValues(EMPTY);
      bumpData();
      onSaved?.(res.payload.day);
    } catch (err) {
      setStatus({ tone: 'high', text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const form = (
      <form onSubmit={submit} noValidate className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <NumberField label="Mission day" value={day} onChange={setDay} min={1} max={MAX_DAY + 30} step={1} error={errors.day} />
          {[...METRIC_KEYS].sort((a, b) => (a === initialMetric ? -1 : b === initialMetric ? 1 : 0)).map((k) => (
            <NumberField key={k} label={METRICS[k].label} unit={METRICS[k].unit} value={values[k]} min={LIMITS[k][0]} max={LIMITS[k][1]}
              onChange={(v) => setValues((s) => ({ ...s, [k]: v }))} error={errors[k]} placeholder="—" />
          ))}
        </div>
        {errors.form && <p className="text-sm text-high">{errors.form}</p>}
        {status && <Notice tone={status.tone}>{status.text}</Notice>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" icon="check" disabled={busy}>{busy ? 'Saving…' : 'Save measurement'}</Button>
          <Button variant="ghost" onClick={() => { setValues(EMPTY); setErrors({}); setStatus(null); }}>Clear</Button>
        </div>
      </form>
  );
  if (bare) return form;
  return (
    <Card eyebrow="Manual entry" title="Record measurements" actions={<span className="text-xs text-ink-3">Stored with source “manual”</span>}>
      {form}
    </Card>
  );
}
