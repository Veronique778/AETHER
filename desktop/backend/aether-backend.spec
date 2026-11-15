# PyInstaller spec – one-file Windows executable of the AETHER backend sidecar.
#   cd desktop/backend && pyinstaller aether-backend.spec --noconfirm
# Output: dist/aether-backend.exe → copied to src-tauri/binaries/aether-backend-<target-triple>.exe
from PyInstaller.utils.hooks import collect_submodules

backend_src = '../../web/backend'
hidden = (collect_submodules('app') + collect_submodules('uvicorn') + ['app.main', 'app.devserver']
          # v0.8: Mission Systems engine (imported lazily by app.mission_engine, so list it explicitly)
          + collect_submodules('mission_systems') + ['scipy.optimize', 'scipy.sparse', 'numpy'])

a = Analysis(
    ['aether_backend.py'],
    pathex=[backend_src],
    hiddenimports=hidden,
    excludes=['pytest', 'httpx', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='aether-backend',
    console=True,          # Tauri reads stdout; the shell starts it without a visible window (CREATE_NO_WINDOW)
    upx=False,
    icon='../src-tauri/icons/icon.ico',
)
