/** AETHER modules as they exist in the Windows application (status words are deliberately conservative). */
export type ModuleInfo = {
  id: string; name: string; tagline: string; icon: 'body' | 'activity' | 'bluetooth' | 'leaf' | 'users' | 'heart' | 'flask';
  what: string; howItWorks: string[]; status: string; demoHere: string | null; anchor?: string;
};

export const MODULES: ModuleInfo[] = [
  { id: 'body', name: 'BODY', tagline: 'Human digital twin', icon: 'body', anchor: '#body',
    what: 'A 3D digital twin that places personal measurements on five body systems: cardiovascular, respiratory, neurological, musculoskeletal and metabolic.',
    howItWorks: ['Surface and X-ray views of the team’s 3D models', 'Each system toggles its own layer; metric tags sit on the related region', 'Region-to-system mapping is an approximate visual aid, not anatomy'],
    status: 'In the Windows app: personal measurement history per account. Here: interactive model only.', demoHere: 'Interactive BODY section on this page' },
  { id: 'phantom', name: 'PHANTOM', tagline: 'Personal change detection', icon: 'activity', anchor: '#phantom',
    what: 'Compares new heart-rate windows with a frozen personal baseline and explains the result as flag, no_flag or insufficient_data.',
    howItWorks: ['5-minute windows, first hour = frozen personal baseline', 'Robust scale: max(3 bpm, 1.4826 · MAD)', 'Flag when the robust z of a window is ≥ 3.5'],
    status: 'Validated only on a pre-registered synthetic benchmark. Not a diagnosis, not clinically validated.', demoHere: 'PHANTOM interactive demo on this page (illustration)' },
  { id: 'biosignals', name: 'BIOSIGNALS', tagline: 'Bluetooth heart-rate sensors', icon: 'bluetooth',
    what: 'Records heart rate (and RR intervals when available) from sensors that expose the standard Bluetooth Heart Rate Service, into the signed-in user’s own database.',
    howItWorks: ['Scan → verify GATT 0x180D / 0x2A37 → record → stop & save', 'Contact loss, stale data and link loss are stored as gaps, never filled', 'Provenance (real sensor vs synthetic) is set by the application, not by the user'],
    status: 'Software path tested with test doubles. Physical Bluetooth hardware: not yet verified. Windows app only.', demoHere: null },
  { id: 'symbiosis', name: 'SYMBIOSIS', tagline: 'Crew ↔ habitat environment', icon: 'leaf',
    what: 'Explores how cabin environment (CO₂, temperature, light, noise) and crew physiology relate in a synthetic mission.',
    howItWorks: ['Habitat zones on a spacecraft twin', 'Association views between environment and crew signals', 'All mission data are synthetic and labelled'],
    status: 'Synthetic mission demonstration in the Windows app.', demoHere: null },
  { id: 'co-orbit', name: 'CO-ORBIT', tagline: 'Crew coordination', icon: 'users',
    what: 'Plans crew schedules under constraints and shows how a physiological change could shift workload.',
    howItWorks: ['Constraint-based schedule of mandatory tasks', 'What-if replanning for a crew member', 'Synthetic crew A01–A04'],
    status: 'Synthetic scheduling demonstration in the Windows app.', demoHere: null },
  { id: 'recovery', name: 'RECOVERY', tagline: 'Recovery environment', icon: 'heart',
    what: 'Guided recovery sessions (breathing, light, sound) with session history.',
    howItWorks: ['Paced-breathing visual', 'Session notes stored locally', 'No therapeutic claim'],
    status: 'Wellbeing prototype in the Windows app; no clinical effect is claimed.', demoHere: null },
  { id: 'mission-lab', name: 'MISSION LAB', tagline: 'Simulation lab', icon: 'flask',
    what: 'Runs what-if mission simulations (duration, radiation context, schedule load) on a synthetic crew engine.',
    howItWorks: ['Scenario presets and parameter sliders', 'Engine runs with reproducible seeds', 'Radiation figures are reference values from published sources'],
    status: 'Synthetic simulation in the Windows app; not a prediction for real missions.', demoHere: null },
];
