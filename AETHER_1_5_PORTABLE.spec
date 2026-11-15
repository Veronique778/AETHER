# AETHER 1.5 (BLE personal) portable Windows build. Run only via BUILD_WINDOWS_1_5.bat on Windows x64 + CPython 3.13.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH)
dist_ui = root / 'web' / 'frontend' / 'dist'
info = dist_ui / 'BUILD_INFO.json'
assert (dist_ui / 'index.html').is_file() and info.is_file(), 'web/frontend/dist missing: run npm run build or scripts/build-release.mjs'
models = sorted((dist_ui / 'models').glob('*.glb'))
assert len(models) == 6, f'expected 6 GLB models in {dist_ui / "models"}, found {len(models)}'
migrations = root / 'web' / 'backend' / 'app' / 'migrations'

hidden = (collect_submodules('app') + collect_submodules('mission_systems') + ['release_smoke']
          # Bluetooth: bleak picks its backend at runtime, so PyInstaller cannot see it statically
          + collect_submodules('bleak') + collect_submodules('winrt')
          + ['webview.platforms.edgechromium', 'webview.platforms.winforms', 'clr', 'pythonnet'])
datas = ([(str(dist_ui), 'web/frontend/dist'), (str(migrations / '*.sql'), 'app/migrations')]
         + collect_data_files('webview') + collect_data_files('winrt'))   # winrt: *.pywinrt projection tables

a = Analysis(
    ['desktop_native.py'],
    pathex=[str(root), str(root / 'web' / 'backend')],
    datas=datas,
    hiddenimports=hidden,
    excludes=['torch', 'tensorflow', 'jax', 'jaxlib', 'sklearn', 'sympy', 'xarray', 'scipy.tests', 'numpy.tests',
              'matplotlib', 'pandas', 'IPython', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'gi', 'fastapi', 'uvicorn',
              'tests', 'fakes'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AETHER_1_5', console=False, debug=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AETHER_1_5_PORTABLE')
