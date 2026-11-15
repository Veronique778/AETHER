import { CREW_HEX, initials } from '../../lib/format';
import { useApp } from '../../state/AppState';
import { cx } from '../../ui';

/** Inline crew-member switcher (radiogroup). Changes the global selected astronaut. */
export function CrewSwitcher({ label = 'Crew member' }: { label?: string }) {
  const { astronauts, astronautId, setAstronautId } = useApp();
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
      {astronauts.map((a, i) => (
        <button key={a.id} type="button" role="radio" aria-checked={a.id === astronautId} tabIndex={a.id === astronautId ? 0 : -1}
          onClick={() => setAstronautId(a.id)}
          onKeyDown={(e) => {
            const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
            if (!d) return;
            e.preventDefault();
            const next = astronauts[(i + d + astronauts.length) % astronauts.length];
            setAstronautId(next.id);
            (e.currentTarget.parentElement?.children[(i + d + astronauts.length) % astronauts.length] as HTMLElement | undefined)?.focus();
          }}
          className={cx('flex min-h-9 items-center gap-2 rounded-full border py-1 pl-1 pr-3 text-sm transition-colors',
            a.id === astronautId ? 'border-teal-300 bg-teal-600/20 text-ink' : 'border-line text-ink-2 hover:border-line-strong')}>
          <span className="grid h-7 w-7 place-items-center rounded-full text-[10px] font-bold text-white" style={{ background: CREW_HEX[a.id] }}>{initials(a.name)}</span>
          {a.name}
        </button>
      ))}
    </div>
  );
}
