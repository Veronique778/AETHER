/* AETHER public release links. Edit this ONE FILE on deployed website; no React rebuild needed.
 * Keep downloadUrl empty until the uploaded build is independently tested and publicly accessible.
 * When available, set status: 'available' and a real HTTPS itch.io (or direct) link.
 */
window.AETHER_RELEASE_CHANNELS = {
  windows: {
    label: 'Windows', arch: 'x64 · Windows 10 / 11',
    status: 'build_pending',
    version: 'AETHER 1.5 Unified · source integrated',
    downloadUrl: '', fileName: '', sha256: '',
    note: 'Latest Live + Demo integration requires a fresh Windows build and clean-machine test.'
  },
  macos: {
    label: 'macOS', arch: 'Apple Silicon / Intel · separate builds',
    status: 'build_pending',
    version: 'Desktop port · build pending',
    downloadUrl: '', fileName: '', sha256: '',
    note: 'Native Cocoa/WebKit package must be built, signed and tested on macOS.'
  },
  linux: {
    label: 'Linux', arch: 'x86_64 · GTK/WebKit2GTK',
    status: 'build_pending',
    version: 'Desktop port · build pending',
    downloadUrl: '', fileName: '', sha256: '',
    note: 'Portable Linux package requires a real Linux build and GUI smoke test.'
  }
};
