import { useState } from 'react';
import { APP_VERSION, DOWNLOAD_FILE_NAME, DOWNLOAD_SHA256, DOWNLOAD_SIZE_MB, PLATFORM, RELEASE_STATUS, downloadAvailable } from '../config/download';
import { EVENT, EVENT_URL, PROJECT_URL, TEAM_MEMBERS, TEAM_NAME } from '../config/project';
import { Icon } from '../vendor/aether/ui';
import { DownloadButton, Logo } from './Hero';
import { SectionHeader } from './common';

export function Download() {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(DOWNLOAD_SHA256); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { setCopied(false); }
  };
  return (
    <section id="download" aria-labelledby="download-title" className="relative px-4 py-24 sm:px-6">
      <div className="glass relative mx-auto max-w-6xl overflow-hidden rounded-[28px] p-6 sm:p-10">
        <div className="hairline absolute inset-x-0 top-0" aria-hidden="true" />
        <SectionHeader id="download" eyebrow="06 · Download" title={<span className="text-gradient">Ready to Explore AETHER?</span>}>
          The website is a lightweight demonstration. The separately packaged desktop application is the research platform: personal accounts,
          local SQLite storage, compatible Bluetooth heart-rate sensors where supported, PHANTOM, BODY history and mission simulation modules. The current Unified desktop update is awaiting OS-specific verified builds.
        </SectionHeader>
        <div className="flex flex-col items-center gap-3">
          <DownloadButton />
          {!downloadAvailable() && <p className="text-sm text-ink-3">New Unified binaries are not yet published. The interactive browser demo works across operating systems.</p>}
        </div>

        <div className="mt-10 grid gap-4 md:grid-cols-3">
          <div className="rounded-2xl border border-line bg-canvas/50 p-5">
            <h3 className="flex items-center gap-2 font-semibold"><Icon name="info" size={17} className="text-teal-300" />Release</h3>
            <dl className="mt-3 space-y-2 text-sm">
              <div><dt className="mono-label">Version</dt><dd className="text-ink">{APP_VERSION}</dd></div>
              <div><dt className="mono-label">Platform</dt><dd className="text-ink">{PLATFORM}</dd></div>
              <div><dt className="mono-label">Status</dt><dd className="text-ink-2">{RELEASE_STATUS}</dd></div>
              {DOWNLOAD_SHA256 && (
                <div><dt className="mono-label">SHA-256 · {DOWNLOAD_FILE_NAME} (≈ {DOWNLOAD_SIZE_MB} MB)</dt>
                  <dd className="mt-1 flex items-start gap-2"><code className="break-all font-mono text-[11px] text-ink-2" data-testid="sha256">{DOWNLOAD_SHA256}</code>
                    <button type="button" onClick={() => void copy()} className="shrink-0 rounded-md border border-line-strong px-2 py-0.5 text-[11px] text-ink hover:border-teal-300" aria-label="Copy SHA-256 checksum">{copied ? 'Copied' : 'Copy'}</button></dd></div>
              )}
            </dl>
          </div>
          <div className="rounded-2xl border border-line bg-canvas/50 p-5">
            <h3 className="flex items-center gap-2 font-semibold"><Icon name="settings" size={17} className="text-teal-300" />System requirements</h3>
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-ink-2">
              <li>Windows 10 or 11, 64-bit</li>
              <li>Microsoft Edge WebView2 Runtime (built into Windows 11)</li>
              <li>≈ 250 MB free disk space; no Python, Node.js or admin rights</li>
              <li>Optional: Bluetooth LE and a heart-rate sensor with the standard Heart Rate Service (chest straps; watches in “broadcast heart rate” mode)</li>
            </ul>
          </div>
          <div className="rounded-2xl border border-line bg-canvas/50 p-5">
            <h3 className="flex items-center gap-2 font-semibold"><Icon name="download" size={17} className="text-teal-300" />Install the portable app</h3>
            <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-ink-2">
              <li>Download the ZIP and check its SHA-256 (PowerShell: <code className="font-mono text-[11px] text-ink">Get-FileHash .\{DOWNLOAD_FILE_NAME}</code>).</li>
              <li>Right-click → <em>Extract All…</em> to a short folder, e.g. <code className="font-mono text-[11px] text-ink">C:\AETHER15</code>.</li>
              <li>Optional check: run <code className="font-mono text-[11px] text-ink">CHECK_BLE_WINDOWS.bat</code>.</li>
              <li>Start <code className="font-mono text-[11px] text-ink">AETHER_1_5.exe</code>. The file is not code-signed, so SmartScreen may ask: <em>More info → Run anyway</em>.</li>
              <li>Create a local account (stays on your PC) and open BIOSIGNALS, BODY or PHANTOM.</li>
            </ol>
          </div>
        </div>
        <div className="mt-4 rounded-2xl border border-attention/40 bg-attention/5 p-5 text-sm text-ink-2">
          <h3 className="flex items-center gap-2 font-semibold text-ink"><Icon name="alert" size={17} className="text-attention" />Scientific limitations</h3>
          <p className="mt-2">AETHER is a research prototype, not a medical device. PHANTOM has been evaluated on synthetic data only; no clinical, human-data or astronaut validation exists yet, and physical Bluetooth hardware has not been verified. A <em>flag</em> is a statistical change, not a diagnosis; <em>no_flag</em> does not mean “healthy”. Only standard Bluetooth Heart Rate Service sensors are supported (Apple Watch is not).</p>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-line px-4 py-10 sm:px-6">
      <div className="mx-auto grid max-w-7xl gap-8 md:grid-cols-[1.2fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2.5"><Logo size={26} /><span className="font-semibold tracking-[0.28em]">AETHER</span></div>
          <p className="mt-3 text-sm text-ink-2">Adaptive Ecosystem for Human Exploration and Resilience.</p>
          <p className="mt-2 text-sm text-ink-2">{TEAM_NAME || 'AETHER project team'} · <a className="text-teal-300 hover:underline" href={EVENT_URL} target="_blank" rel="noopener noreferrer">{EVENT}</a></p>
          {TEAM_MEMBERS.length > 0 && <ul className="mt-2 text-xs text-ink-3">{TEAM_MEMBERS.map((m) => <li key={m}>{m}</li>)}</ul>}
          {PROJECT_URL && <p className="mt-2 text-sm"><a className="text-teal-300 hover:underline" href={PROJECT_URL} target="_blank" rel="noopener noreferrer">Project page</a></p>}
        </div>
        <nav aria-label="Footer">
          <p className="mono-label mb-2">On this page</p>
          <ul className="grid grid-cols-2 gap-1 text-sm">
            {[['#problem', 'Problem'], ['#body', 'Interactive BODY'], ['#phantom', 'PHANTOM demo'], ['#evidence', 'Evidence & sources'], ['#modules', 'Modules'], ['#download', 'Download']].map(([h, l]) => (
              <li key={h}><a href={h} className="text-ink-2 hover:text-ink">{l}</a></li>
            ))}
          </ul>
        </nav>
        <div className="text-xs leading-relaxed text-ink-3">
          <p>This is an independent student project created for the NASA International Space Apps Challenge. It is not affiliated with, endorsed by or sponsored by NASA. NASA sources are cited as public scientific references only.</p>
          <p className="mt-2">Research prototype · not for clinical or operational use · all website data are synthetic and run entirely in your browser; nothing is sent anywhere.</p>
        </div>
      </div>
    </footer>
  );
}
