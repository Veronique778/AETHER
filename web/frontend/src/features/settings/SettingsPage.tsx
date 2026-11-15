import { useRef, useState, type ReactNode } from 'react';
import { desktop, isDesktop } from '../../desktop/bridge';
import { exportLocalData, importLocalData } from '../../desktop/localData';
import { downloadText } from '../../lib/format';
import { API_BASE, autoThemeAt, IS_MOBILE_BUILD, MOBILE_API_CONFIGURED, useApp, type Role, type TextScale, type ThemePref } from '../../state/AppState';
import { Button, Card, Notice, PageHeader, Pill, Segmented } from '../../ui';

function Row({ title, hint, children }: { title: string; hint: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-2 border-t border-line py-4 first:border-t-0 first:pt-0 md:grid-cols-[260px_1fr] md:gap-6">
      <div><div className="font-medium text-ink">{title}</div><div className="text-sm text-ink-3">{hint}</div></div>
      <div className="flex flex-wrap items-start gap-2">{children}</div>
    </div>
  );
}

/** User settings. All preferences persist in this browser (localStorage). */
export function SettingsPage() {
  const app = useApp();
  return (
    <div className="max-w-4xl">
      <PageHeader eyebrow="AETHER" title="Settings" description="Display, accessibility, data source and viewing role. Saved in this browser." />
      <div className="space-y-5">
        <Card title="Display">
          <Row title="Display mode" hint={<>Light (dark text) is easier to read in normal cabin lighting; dark suits dim / pre-sleep lighting. Auto follows mission time (light 07:00–20:00). Now: <strong>{app.effectiveTheme}</strong>{app.theme === 'auto' && ` (auto at ${String(Math.floor(app.hour)).padStart(2, '0')}:00 → ${autoThemeAt(app.hour)})`}.</>}>
            <Segmented label="Display mode" value={app.theme} onChange={(v: ThemePref) => app.setTheme(v)} options={[{ value: 'dark', label: 'Dark', icon: 'moon' }, { value: 'light', label: 'Light', icon: 'sun' }, { value: 'auto', label: 'Auto (mission time)', icon: 'clock' }]} />
          </Row>
          <Row title="Text size" hint="Scales all text and spacing that depends on it.">
            <Segmented label="Text size" value={app.textScale} onChange={(v: TextScale) => app.setTextScale(v)} options={[{ value: '1', label: '100 %' }, { value: '1.12', label: '112 %' }, { value: '1.25', label: '125 %' }]} />
          </Row>
          <Row title="Reduce motion" hint="Stops non-essential animation (camera easing, drifting scenery, plant sway). Follows the OS setting by default.">
            <Segmented label="Reduce motion" value={app.reducedMotion ? 'on' : 'off'} onChange={(v) => app.setReducedMotion(v === 'on')} options={[{ value: 'off', label: 'Off' }, { value: 'on', label: 'On' }]} />
          </Row>
        </Card>
        <Card title="Data source">
          <Row title="Mode" hint={IS_MOBILE_BUILD
            ? 'This mobile build is restricted to the offline synthetic demo. Personal mobile mode is not enabled.'
            : <>Live Mode uses the backend at <code>{API_BASE}</code> for personal measurements. Mission research and interactive previews are available alongside your account, with their own data-source labels. Demo Mode is an offline preview without personal records.</>}>
            {IS_MOBILE_BUILD ? (
              <>
                <Pill tone="attention" icon="database">Offline Demo only</Pill>
                <Notice tone="unknown" className="w-full" title="Mobile Personal mode is pending">
                  {MOBILE_API_CONFIGURED
                    ? 'VITE_API_URL is set, but mobile live mode remains disabled until HTTPS Mission Hub integration is validated.'
                    : 'For a future integration build, set VITE_API_URL to the HTTPS Mission Hub endpoint. Do not use the phone WebView localhost as the server address.'}
                </Notice>
              </>
            ) : (
              <>
                <Segmented label="Data mode" value={app.mode} onChange={app.setMode} options={[{ value: 'live', label: 'Live Mode', icon: 'link' }, { value: 'demo', label: 'Demo Mode', icon: 'database' }]} />
                <span className="w-full text-sm text-ink-3">Connection: {app.connection}{app.backendVersion && ` · API ${app.backendVersion}`}</span>
                {app.mode === 'live' && <Button size="sm" icon="reset" onClick={app.retry}>Re-check backend</Button>}
              </>
            )}
          </Row>
          <Row title="Default astronaut" hint="Used by BODY, PHANTOM, RECOVERY and MISSION LAB.">
            <select aria-label="Default astronaut" className="field !w-auto" value={app.astronautId} onChange={(e) => app.setAstronautId(e.target.value)}>
              {app.astronauts.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.role}</option>)}
            </select>
          </Row>
        </Card>
        <LocalDataCard />
        <Card title="UI viewing mode">
          <Notice tone="unknown" className="mb-4">This is a UI preview setting only. It is not authentication and never grants access; the backend must authorize every request independently.</Notice>
          <Row title="Preview" hint="Changes the interface presentation only; it does not change which records the server permits you to access.">
            <Segmented label="UI viewing mode" value={app.role} onChange={(r: Role) => app.setRole(r)} options={[{ value: 'crew', label: 'Crew preview' }, { value: 'flight-surgeon', label: 'Medical review preview' }]} />
            <Pill tone="info" className="w-fit">UI preview · no permission change</Pill>
          </Row>
        </Card>
      </div>
    </div>
  );
}

/** Export / import of locally stored data (preferences, saved experiments, confirmed plans). */
function LocalDataCard() {
  const file = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const count = Object.keys(exportLocalData().items).length;
  return (
    <Card title="Local data">
      <Row title="Saved on this device" hint={<>Preferences, saved MISSION LAB experiments and confirmed CO-ORBIT plans ({count} item{count === 1 ? '' : 's'}). Measurements and recovery sessions are stored by the backend{isDesktop && desktop?.dataDir ? <> in <code className="break-all">{desktop.dataDir}</code></> : ''}.</>}>
        <Button size="sm" icon="download" onClick={() => downloadText(`AETHER_local-data_${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(exportLocalData(), null, 2), 'application/json')}>Export local data</Button>
        <Button size="sm" icon="plus" onClick={() => file.current?.click()}>Import local data…</Button>
        <input ref={file} type="file" accept="application/json,.json" className="hidden" aria-label="AETHER local data file"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = '';
            if (!f) return;
            f.text().then((t) => { const n = importLocalData(t); setMsg({ ok: true, text: `Imported ${n} item${n === 1 ? '' : 's'}. Reload AETHER to apply preferences.` }); },
              (err: Error) => setMsg({ ok: false, text: err.message })).catch((err: Error) => setMsg({ ok: false, text: err.message }));
          }} />
        <span className="w-full text-sm text-ink-3">Use this to move data between the browser version and the desktop app. Import adds or replaces AETHER items only; nothing is deleted.</span>
        {msg && <Notice tone={msg.ok ? 'good' : 'high'} className="w-full">{msg.text}</Notice>}
      </Row>
    </Card>
  );
}
