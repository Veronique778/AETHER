import { Icon, type IconName } from '../vendor/aether/ui';
import { Cite, Reveal, SectionHeader } from './common';

const POINTS: { icon: IconName; title: string; text: string; cite: string[] }[] = [
  { icon: 'orbit', title: 'Five hazards at once', cite: ['hazards'],
    text: 'NASA’s Human Research Program groups the dangers of spaceflight into five hazards: radiation, isolation and confinement, distance from Earth, altered gravity, and a hostile closed environment. A Mars round trip would take roughly three years.' },
  { icon: 'alert', title: 'Many physiological risks', cite: ['risks', 'research'],
    text: 'HRP tracks risks across human physiology, behavioural performance and space radiation, and runs ongoing investigations of sleep, activity, fluid shifts and immune changes.' },
  { icon: 'heart', title: 'The body changes over a mission', cite: ['twins'],
    text: 'The NASA Twins Study documented changes across many body systems in one astronaut during a 340-day ISS mission compared with his identical twin on Earth.' },
  { icon: 'moon', title: 'Sleep is not what is scheduled', cite: ['sleep'],
    text: 'Astronauts on Shuttle and ISS missions slept about six hours per night, despite 8.5 hours scheduled — a recognised risk in its own right.' },
];

export function Problem() {
  return (
    <section id="problem" aria-labelledby="problem-title" className="relative px-4 py-20 sm:px-6">
      <SectionHeader id="problem" eyebrow="01 · The problem" title="Far from Earth, every crew member is their own reference">
        Long missions cannot rely on population thresholds or a doctor next door. AETHER explores how to notice a meaningful
        change in <em>one person</em> early, explain it, and say clearly when the data are not enough.
      </SectionHeader>
      <ul className="mx-auto grid max-w-6xl gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {POINTS.map((p) => (
          <Reveal as="li" key={p.title} className="glass rounded-2xl p-5">
            <span className="grid h-10 w-10 place-items-center rounded-xl border border-teal-300/40 bg-teal-300/10 text-teal-300"><Icon name={p.icon} size={20} /></span>
            <h3 className="mt-4 text-lg font-semibold text-ink">{p.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-2">{p.text}<Cite ids={p.cite} /></p>
          </Reveal>
        ))}
      </ul>
      <p className="mx-auto mt-6 max-w-3xl text-center text-xs text-ink-3">
        Sources open in a new tab. NASA Open Science Data Repository (OSDR) research data provide reference context in the app<Cite ids={['osdr']} />; they are never used as anyone’s personal baseline.
      </p>
    </section>
  );
}
