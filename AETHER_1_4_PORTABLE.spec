# AETHER 1.4 portable Windows build. Run only via BUILD_PORTABLE_1_4_WINDOWS.bat on Windows x64.
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from pathlib import Path
root = Path(SPECPATH)
dist_ui = root / 'web' / 'frontend' / 'dist-offline'
models = sorted((dist_ui / 'models').glob('*.glb'))
assert len(models) == 6, f'expected 6 GLB models in {dist_ui / "models"}, found {len(models)}'
assert (dist_ui / 'BUILD_INFO.json').exists(), 'dist-offline was not produced by scripts/build-offline.mjs'
a = Analysis(
    ['desktop_native.py'],
    pathex=[str(root / 'web' / 'backend')],
    datas=[(str(dist_ui), 'web/frontend/dist-offline')] + collect_data_files('webview'),
    hiddenimports=collect_submodules('app') + collect_submodules('mission_systems') + collect_submodules('bleak')
                  + ['webview.platforms.edgechromium', 'webview.platforms.winforms', 'clr', 'pythonnet'],
    excludes=['torch', 'tensorflow', 'jax', 'jaxlib', 'sklearn', 'sympy', 'xarray', 'scipy.tests', 'numpy.tests',
              'matplotlib', 'pandas', 'pytest', 'IPython', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'gi', 'fastapi', 'uvicorn'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AETHER_1_4', console=False, debug=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AETHER_1_4_PORTABLE')
