"""Linux harness: run the Python code FROZEN INSIDE a repacked AETHER_1_5.exe (not the source tree).

Loads `app.*`, `release_smoke` and the `desktop_native` entry script as code objects from the EXE's PyInstaller
archive, with sys._MEIPASS pointing at the portable's _internal folder (frontend dist, models, migrations).
Stdlib and third-party wheels come from the local CPython 3.13 (the Windows .pyd files cannot load on Linux).
This verifies the archive contents and the release smoke against the packaged assets — NOT the Windows bootloader,
WebView2 or the radio.

    python tools/frozen_harness.py PORTABLE_DIR -- <desktop_native args>
"""
import importlib.abc
import importlib.util
import marshal
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pyi_archive import CArchive, PYZ  # noqa: E402

portable = Path(sys.argv[1]).resolve()
args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
arc = CArchive(str(portable / 'AETHER_1_5.exe'))
pyz = PYZ(arc.extract(next(e for e in arc.entries if e['name'] == 'PYZ.pyz')))
internal = portable / '_internal'
OWN = ('app', 'release_smoke')


class FrozenFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] not in OWN or name not in pyz.toc:
            return None
        typ = pyz.toc[name][0]
        rel = name.replace('.', os.sep)
        origin = str(internal / rel / '__init__.py') if typ == 1 else str(internal / (rel + '.py'))
        spec = importlib.util.spec_from_loader(name, self, origin=origin, is_package=typ == 1)
        if typ == 1:
            spec.submodule_search_locations = [str(internal / rel)]
        spec.has_location = True
        return spec

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        _t, code = pyz.code(module.__name__)
        module.__file__ = module.__spec__.origin
        exec(code, module.__dict__)


sys.meta_path.insert(0, FrozenFinder())
sys.frozen = True
sys._MEIPASS = str(internal)
wrapper = Path(os.environ.get('AETHER_HARNESS_WRAPPER', ''))
if wrapper.is_file():
    sys.executable = str(wrapper)              # the restart phase re-launches "the EXE" = this harness
dn = marshal.loads(arc.extract(next(e for e in arc.entries if e['name'] == 'desktop_native')))
sys.argv = ['AETHER_1_5.exe'] + args
g = {'__name__': '__main__', '__file__': str(portable / 'desktop_native.py')}
sys.modules['desktop_native'] = type(sys)('desktop_native')
sys.modules['desktop_native'].__dict__.update(g)
exec(dn, sys.modules['desktop_native'].__dict__)
