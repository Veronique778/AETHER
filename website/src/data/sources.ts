/** Sources cited on the site. Each URL was opened during the release check (README_DEPLOY.md, "Link check"). */
export type Source = { id: string; label: string; detail: string; url: string };

export const SOURCES: Record<string, Source> = {
  hazards: { id: 'hazards', label: 'NASA HRP — 5 Hazards of Human Spaceflight', detail: 'Radiation, isolation & confinement, distance from Earth, gravity fields, hostile/closed environments.', url: 'https://www.nasa.gov/hrp/hazards/' },
  risks: { id: 'risks', label: 'NASA HRP — Risks of Human Spaceflight', detail: 'The HRP risk list, grouped into human physiology, behavioural performance and space radiation.', url: 'https://www.nasa.gov/hrp/risks/' },
  research: { id: 'research', label: 'NASA HRP — Ongoing HRP research', detail: 'Current investigations on sleep, activity, fluid shifts, immune biomarkers and multiple body systems.', url: 'https://www.nasa.gov/hrp/ongoing-hrp-research/' },
  osdr: { id: 'osdr', label: 'NASA Biological & Physical Sciences data — Open Science Data Repository (OSDR)', detail: 'Open space-biology and human research data used for reference context.', url: 'https://science.nasa.gov/biological-physical/data/' },
  twins: { id: 'twins', label: 'Garrett-Bakelman et al. 2019, Science — NASA Twins Study', detail: 'Multidimensional changes in one astronaut over a year-long mission.', url: 'https://doi.org/10.1126/science.aau8650' },
  sleep: { id: 'sleep', label: 'Barger et al. 2014, Lancet Neurology', detail: 'Sleep deficiency and hypnotic use in astronauts on Shuttle and ISS missions.', url: 'https://doi.org/10.1016/S1474-4422(14)70122-X' },
  nist: { id: 'nist', label: 'NIST/SEMATECH e-Handbook — detection of outliers', detail: 'Modified z-score rule |M| > 3.5 (Iglewicz & Hoaglin).', url: 'https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm' },
  mad: { id: 'mad', label: 'Rousseeuw & Croux 1993, JASA', detail: 'Robust scale estimation; 1.4826 · MAD as a consistent estimate of σ.', url: 'https://doi.org/10.1080/01621459.1993.10476408' },
  hrs: { id: 'hrs', label: 'Bluetooth SIG — Heart Rate Service', detail: 'Standard GATT service 0x180D, Heart Rate Measurement 0x2A37.', url: 'https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/' },
  mmash: { id: 'mmash', label: 'MMASH dataset (PhysioNet)', detail: 'Multilevel Monitoring of Activity and Sleep in Healthy people — candidate for future human-data validation.', url: 'https://physionet.org/content/mmash/1.0.0/' },
};
