/**
 * Packages the backend sidecar with PyInstaller and places it where Tauri expects it:
 *   src-tauri/binaries/aether-backend-<rust target triple>[.exe]
 * Requires: Python 3.11+ with desktop/backend/requirements-desktop.txt installed, and rustc (for the triple).
 *   PYTHON=path\to\python.exe node scripts/build-backend.mjs
 */
import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3');
const triple = /host: (\S+)/.exec(execFileSync('rustc', ['-vV'], { encoding: 'utf8' }))?.[1];
if (!triple) throw new Error('Could not read the Rust host triple from `rustc -vV`.');
const ext = process.platform === 'win32' ? '.exe' : '';
const backendDir = join(root, 'backend');

console.log(`[backend] PyInstaller with ${python} → target ${triple}`);
execFileSync(python, ['-m', 'PyInstaller', 'aether-backend.spec', '--noconfirm', '--clean'], { cwd: backendDir, stdio: 'inherit' });
const built = join(backendDir, 'dist', `aether-backend${ext}`);
if (!existsSync(built)) throw new Error(`PyInstaller output not found: ${built}`);
mkdirSync(join(root, 'src-tauri', 'binaries'), { recursive: true });
const dest = join(root, 'src-tauri', 'binaries', `aether-backend-${triple}${ext}`);
copyFileSync(built, dest);
console.log(`[backend] sidecar ready: ${dest}`);
