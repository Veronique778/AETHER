"""Path shim: the Mission Systems package now lives in web/backend/mission_systems (single source).

The original Kivy V2 entry points (modules/symbiosis.py, coorbit.py, mission_lab.py, run_mission_systems.py)
keep importing `mission_systems.*` unchanged; this shim redirects them to the integrated package.
"""
from pathlib import Path

_real = Path(__file__).resolve().parents[3] / 'web' / 'backend' / 'mission_systems'
__path__ = [str(_real)]
exec(compile((_real / '__init__.py').read_text(encoding='utf-8'), str(_real / '__init__.py'), 'exec'))
