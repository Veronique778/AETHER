import type { MetricKey } from '../api/types';

/**
 * Why each BODY metric is tracked, which NASA HRP risk it relates to and which checked source supports that
 * (ids match the backend evidence library, /api/science/evidence). Static so it also works in Demo Mode.
 */
export const METRIC_SCIENCE: Record<MetricKey, { why: string; risk: string; sources: string[]; limitation: string }> = {
  heart_rate_bpm: {
    why: 'Long-duration flight changes the cardiovascular system (the NASA Twins Study reported carotid changes after 340 days on the ISS). Resting heart rate is a coarse, cheap load indicator.',
    risk: 'Risk of Cardiovascular Adaptations', sources: ['GARRETT-BAKELMAN-2019', 'CSA-ISS-SCIENCE'],
    limitation: 'Heart rate alone cannot show vascular or cardiac structural change; values here are synthetic.',
  },
  sleep_hours: {
    why: 'Astronauts slept about 6 h per night on Shuttle and ISS missions despite 8.5 h scheduled; sleep loss is an HRP risk in its own right.',
    risk: 'Risk of Inadequate Sleep and Irregular Schedules', sources: ['BARGER-2014', 'BASNER-2013'],
    limitation: 'Duration only – no sleep staging or timing; synthetic values.',
  },
  fatigue_1_10: {
    why: 'Self-reported fatigue is a behavioural-health signal under isolation and irregular schedules; the Mars-520 analogue showed individual differences in sleep and vigilance.',
    risk: 'Risk of Behavioral Changes and Psychiatric Disorders', sources: ['BASNER-2013', 'NASA-HAZARDS'],
    limitation: 'Subjective 1–10 scale, not a validated instrument in AETHER.',
  },
  reaction_ms: {
    why: 'Vigilance / reaction tests are used to track cognitive performance in isolation and after sleep loss (Mars-520 used psychomotor vigilance testing).',
    risk: 'Risk of Behavioral Changes and Psychiatric Disorders', sources: ['BASNER-2013'],
    limitation: 'Single reaction-time number; not a validated cognitive battery.',
  },
  activity_minutes: {
    why: 'Unloading causes bone loss of roughly 1–1.5 % per month and fitness loss; exercise is the main countermeasure. Mars-520 crews became progressively less active.',
    risk: 'Risk of Spaceflight-Induced Bone Changes · Reduced Cardiorespiratory and Musculoskeletal Fitness', sources: ['OCHMO-TB-030', 'BASNER-2013'],
    limitation: 'Minutes only – no load, intensity or bone measurement.',
  },
};
