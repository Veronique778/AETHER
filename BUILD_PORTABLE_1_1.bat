@echo off
cd /d "%~dp0"
python -c "import sys,sysconfig; assert sys.version_info[:2]==(3,13) and not sysconfig.get_config_var('Py_GIL_DISABLED')" || exit /b 1
python -m pip install --only-binary=:all: --no-binary=proxy-tools pyinstaller "pywebview>=5,<7" "bleak>=1.1,<3" "numpy>=1.26,<3" "scipy>=1.11,<2" "pydantic>=2.6,<3" || exit /b 1
python -m PyInstaller --noconfirm --clean AETHER_1_1_PORTABLE.spec
