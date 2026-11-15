"""Run from PyCharm green button to prepare the Android/iOS Capacitor project.
Requires Node.js, internet on first install; native builds need Android Studio / Xcode.
Does NOT claim to create an APK/IPA in Python alone.
"""
from pathlib import Path
import os, shutil, subprocess, sys
ROOT = Path(__file__).resolve().parent
FRONT = ROOT / 'web' / 'frontend'
MOBILE = ROOT / 'mobile'

def run(args, cwd, env=None):
    print('[AETHER MOBILE]', ' '.join(map(str, args)), flush=True)
    subprocess.run(args, cwd=cwd, env=env, check=True)

def main():
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm') or shutil.which('npm')
    if not npm:
        raise RuntimeError('Install Node.js LTS: https://nodejs.org')
    if not (FRONT / 'node_modules' / 'vite').exists():
        run([npm, 'ci'], FRONT)
    env = os.environ.copy()
    env['VITE_MOBILE_APP'] = '1'
    env['VITE_DATA_MODE'] = 'demo'
    run([npm, 'run', 'build'], FRONT, env)
    if not (MOBILE / 'node_modules' / '@capacitor' / 'cli').exists():
        run([npm, 'install'], MOBILE)
    cap = MOBILE / 'node_modules' / '.bin' / ('cap.cmd' if os.name == 'nt' else 'cap')
    if not cap.exists():
        raise RuntimeError('Capacitor CLI was not installed')
    for platform in ('android', 'ios'):
        if (MOBILE / platform).exists():
            run([str(cap), 'sync', platform], MOBILE)
    print('\n[AETHER MOBILE] Web assets built. Next steps:')
    print('  cd mobile')
    print('  npx cap add android    (first time, on Windows/macOS)')
    print('  npx cap open android   (Android Studio builds APK)')
    print('  npx cap add ios        (first time, macOS only)')
    print('  npx cap open ios       (Xcode builds/signs iOS app)')
    print('  After changing frontend: run BUILD_MOBILE.py again to sync native projects.')

if __name__ == '__main__':
    try: main()
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print('[AETHER MOBILE] ERROR:', exc, file=sys.stderr)
        raise SystemExit(1)
