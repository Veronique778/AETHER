# Build only on a developer Windows machine, using precompiled dependencies.
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from pathlib import Path
root=Path(SPECPATH)
a=Analysis(['desktop_native.py'],pathex=[str(root/'web'/'backend')],
 datas=[(str(root/'web'/'frontend'/'dist-offline'),'web/frontend/dist-offline')]+collect_data_files('webview'),
 hiddenimports=collect_submodules('app')+collect_submodules('bleak')+['webview.platforms.edgechromium','webview.platforms.winforms','clr','pythonnet'],
 excludes=['torch','tensorflow','jax','jaxlib','sklearn','sympy','xarray','scipy.tests','numpy.tests','matplotlib','pandas','pytest','IPython','PyQt5','PyQt6','PySide2','PySide6','gi'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='AETHER_1_1',console=False,debug=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='AETHER_1_1_PORTABLE')
