@echo off
cd /d "%~dp0"
python -c "import sys,sysconfig; assert sys.version_info[:2]==(3,13) and not sysconfig.get_config_var('Py_GIL_DISABLED'), 'Use standard Python 3.13, not 3.13t'" || exit /b 1
python -m pip install --only-binary=:all: "bleak>=1.1,<3"
