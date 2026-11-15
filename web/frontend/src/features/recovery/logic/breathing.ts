/**
 * Zero-G Garden biofeedback – paced breathing. The user holds a key/pointer while
 * inhaling. "Coherence" = share of samples where the user's phase matches the pacer.
 * This is behavioural feedback on pacing only; it does not measure physiology.
 */
export type Pace = { breathsPerMin: number; inhaleShare: number };

export function pacerPhase(tSec: number, p: Pace): { inhale: boolean; progress: number } {
  const cycle = 60 / p.breathsPerMin;
  const inhaleLen = cycle * p.inhaleShare;
  const t = ((tSec % cycle) + cycle) % cycle;
  return t < inhaleLen ? { inhale: true, progress: t / inhaleLen } : { inhale: false, progress: (t - inhaleLen) / (cycle - inhaleLen) };
}

export class CoherenceMeter {
  private match = 0;
  private total = 0;
  private recent: boolean[] = [];
  constructor(private window = 120) {}
  /** Ignore the first 300 ms after each pacer transition – a fair reaction allowance. */
  sample(userInhale: boolean, pacer: { inhale: boolean; progress: number }, cycleSec: number, share: number) {
    const phaseLen = pacer.inhale ? cycleSec * share : cycleSec * (1 - share);
    if (pacer.progress * phaseLen < 0.3) return;
    const ok = userInhale === pacer.inhale;
    this.total++;
    if (ok) this.match++;
    this.recent.push(ok);
    if (this.recent.length > this.window) this.recent.shift();
  }
  get overall() { return this.total ? this.match / this.total : 0; }
  get current() { return this.recent.length ? this.recent.filter(Boolean).length / this.recent.length : 0; }
  get samples() { return this.total; }
}
