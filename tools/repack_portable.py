"""Repackage the AETHER 1.5 Windows Portable with the updated pure-Python modules and the rebuilt frontend.

WHY: the release machine for this change has no Windows/PyInstaller. The original AETHER_1_5.exe is a PyInstaller 6
onedir build of CPython 3.13 (PYZ magic f30d0d0a). Pure-Python modules are stored as marshalled code objects, so a
module compiled by any CPython 3.13.x is byte-compatible. This script:

  1. reads the CArchive appended to the original EXE (bootloader bytes are copied unchanged),
  2. rebuilds PYZ.pyz: every entry copied verbatim except modules whose source changed (compiled here with 3.13),
     plus new modules (app.devices.simulated, release_smoke),
  3. replaces the `desktop_native` entry-point script,
  4. replaces _internal/web/frontend/dist with the freshly built bundle (new content-hashed asset names),
  5. writes BUILD_PROVENANCE.json (what was replaced, hashes) and verifies the new archive by re-reading it.

It does NOT run the EXE (no Windows here). A real PyInstaller build: BUILD_WINDOWS_1_5.bat + AETHER_1_5_PORTABLE.spec.

    python tools/repack_portable.py ORIGINAL_PORTABLE_DIR OUTPUT_DIR
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import marshal
import shutil
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pyi_archive import CArchive, PYZ, build_carchive, build_pyz  # noqa: E402

BACKEND = ROOT / 'web' / 'backend'
EXE = 'AETHER_1_5.exe'
NEW_MODULES = ('app.devices.simulated',)


def module_source(name: str, typ: int) -> Path | None:
    if name in ('release_smoke',):
        return ROOT / 'release_smoke.py'
    rel = name.replace('.', '/')
    for cand in ([BACKEND / rel / '__init__.py'] if typ == 1 else []) + [BACKEND / f'{rel}.py', BACKEND / rel / '__init__.py']:
        if cand.is_file():
            return cand
    return None


def compile_for_pyz(path: Path, name: str) -> bytes:
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
    return marshal.dumps(compile(path.read_bytes(), rel.split('web/backend/')[-1], 'exec', dont_inherit=True, optimize=0))


def norm(co):
    return (co.co_code, tuple(norm(c) if hasattr(c, 'co_code') else repr(c) for c in co.co_consts), co.co_names, co.co_varnames)


def main(src_dir: str, out_dir: str):
    assert sys.version_info[:2] == (3, 13), 'must compile with CPython 3.13 (the frozen runtime is python313.dll)'
    src, out = Path(src_dir), Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out)
    arc = CArchive(str(src / EXE))
    pyz_entry = next(e for e in arc.entries if e['name'] == 'PYZ.pyz')
    pyz = PYZ(arc.extract(pyz_entry))
    assert pyz.pymagic == importlib.util.MAGIC_NUMBER, 'bytecode magic mismatch'
    entries, changed, added = [], [], []
    for name in sorted(pyz.toc):
        typ, raw = pyz.get(name)
        if raw is not None and name.split('.')[0] in ('app', 'release_smoke'):
            path = module_source(name, typ)
            if path is not None:
                new = compile_for_pyz(path, name)
                if norm(marshal.loads(new)) != norm(marshal.loads(raw)):
                    raw = new
                    changed.append(name)
        entries.append((name, typ, raw))
    have = {n for n, _, _ in entries}
    # new modules introduced by the BLE personal integration (a PyInstaller build collects them via
    # collect_submodules('app')). Other source modules absent from the original build are NOT added (parity).
    for name in NEW_MODULES:
        if name not in have:
            entries.append((name, 0, compile_for_pyz(module_source(name, 0), name)))
            added.append(name)
    if 'release_smoke' not in have:
        entries.append(('release_smoke', 0, compile_for_pyz(ROOT / 'release_smoke.py', 'release_smoke')))
        added.append('release_smoke')
    entries.sort(key=lambda e: e[0])
    new_pyz = build_pyz(pyz.pymagic, entries)
    items = []
    for e in arc.entries:
        if e['name'] == 'PYZ.pyz':
            items.append({'name': 'PYZ.pyz', 'tc': 'z', 'cflag': 0, 'ulen': len(new_pyz), 'raw': new_pyz})
        elif e['name'] == 'desktop_native':
            code = marshal.dumps(compile((ROOT / 'desktop_native.py').read_bytes(), 'desktop_native.py', 'exec', dont_inherit=True))
            comp = zlib.compress(code, 9)
            items.append({'name': 'desktop_native', 'tc': e['tc'], 'cflag': 1, 'ulen': len(code), 'raw': comp})
        else:
            items.append({'name': e['name'], 'tc': e['tc'], 'cflag': e['cflag'], 'ulen': e['ulen'], 'raw': arc.raw(e)})
    exe_bytes = build_carchive(arc.bootloader, items, arc.pyvers, arc.pylib, arc.tail)
    (out / EXE).write_bytes(exe_bytes)

    # frontend
    dist_dst = out / '_internal' / 'web' / 'frontend' / 'dist'
    shutil.rmtree(dist_dst)
    shutil.copytree(ROOT / 'web' / 'frontend' / 'dist', dist_dst)

    # verification by re-reading
    check = CArchive(str(out / EXE))
    assert check.bootloader == arc.bootloader, 'bootloader changed'
    cp = PYZ(check.extract(next(e for e in check.entries if e['name'] == 'PYZ.pyz')))
    for name in changed + added:
        t, co = cp.code(name)
        p = module_source(name, t) or ROOT / 'release_smoke.py'
        assert norm(co) == norm(compile(p.read_bytes(), 'x', 'exec', dont_inherit=True)), name
    dn = marshal.loads(check.extract(next(e for e in check.entries if e['name'] == 'desktop_native')))
    assert norm(dn) == norm(compile((ROOT / 'desktop_native.py').read_bytes(), 'x', 'exec', dont_inherit=True))
    assert len(cp.toc) == len(pyz.toc) + len(added)
    sha = lambda b: hashlib.sha256(b).hexdigest()
    info = {'method': 'repackaged (PyInstaller 6 CArchive/PYZ rewritten by tools/repack_portable.py); NOT a fresh PyInstaller run',
            'executed_on_windows': False, 'python_used_to_compile': sys.version.split()[0],
            'original_exe_sha256': sha((src / EXE).read_bytes()), 'new_exe_sha256': sha(exe_bytes),
            'bootloader_sha256_unchanged': sha(arc.bootloader), 'pyz_entries_before': len(pyz.toc), 'pyz_entries_after': len(cp.toc),
            'modules_replaced': changed, 'modules_added': added, 'entry_script_replaced': 'desktop_native',
            'frontend_dist_replaced': True,
            'frontend_assets': sorted(p.name for p in (dist_dst / 'assets').iterdir()),
            'unchanged': 'bootloader, python313.dll, all .pyd/.dll, bleak/winrt/webview/numpy/scipy/pydantic/argon2 modules, '
                         'models, migrations', 'hardware_verified': False}
    (out / 'BUILD_PROVENANCE.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main(*sys.argv[1:3])
