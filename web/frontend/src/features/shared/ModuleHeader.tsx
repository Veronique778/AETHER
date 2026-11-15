import type { ReactNode } from 'react';
import { MODULES } from '../../layout/AppShell';
import { useApp } from '../../state/AppState';
import { Icon } from '../../ui';

/** Module page header with the module's identity colour. Descriptions are hidden in compact density. */
export function ModuleHeader({ module, title, description, actions }: { module: string; title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  const { density } = useApp();
  const m = MODULES.find((x) => x.path === module)!;
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 max-w-3xl items-start gap-3">
        <span className="mt-1 grid h-11 w-11 shrink-0 place-items-center rounded-xl border" style={{ color: m.accent, borderColor: `color-mix(in srgb, ${m.accent} 40%, transparent)`, background: `color-mix(in srgb, ${m.accent} 10%, transparent)` }}>
          <Icon name={m.icon} size={22} />
        </span>
        <div className="min-w-0">
          <div className="mono-label" style={{ color: m.accent }}>{m.name} · {m.sub}</div>
          <h1 className="mt-0.5 text-2xl font-semibold text-ink">{title}</h1>
          {description && density === 'expanded' && <p className="mt-1 text-ink-2">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
