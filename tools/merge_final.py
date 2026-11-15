#!/usr/bin/env python3
"""AETHER 1.0 FINAL – safe three-way packaging merge.

    python tools/merge_final.py AETHER_1_0_BACKEND.zip AETHER_FINAL_BACKEND_PATCH.zip AETHER_FINAL_FRONTEND_PATCH.zip \
        [--out AETHER_1_0_FINAL_MERGED.zip] [--report MERGE_REPORT.md] [--allow-identical]

1. Extracts the original project (archive 1) after validating every entry (no absolute paths, no `..`, no drive letters,
   no symlinks, no duplicate names) – ZIP-slip / path traversal is rejected, nothing is written outside the work dir.
2. Overlays the backend patch ONLY into backend-owned paths and the frontend patch ONLY into frontend/desktop-owned paths.
   A patch file outside its owner's paths aborts the merge.
3. Refuses a merge where both patches contain the same file (unless the bytes are identical and --allow-identical is set).
4. Never deletes files: patches add or replace files only. Caches, virtual environments, node_modules and build output
   inside the patches are ignored and listed in the report.
5. Writes AETHER_1_0_FINAL_MERGED.zip and a Markdown merge report.

The report says explicitly that NO test was run on the merged tree – run the test commands it lists before release.
Exit codes: 0 ok · 2 usage / missing archive · 3 unsafe archive entry · 4 ownership violation · 5 overlapping change.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import stat
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

# Ownership rules (release brief §1). Patterns are POSIX paths relative to the project root (`AETHER/`).
BACKEND_OWNED = ('web/backend/', 'docs/API_CONTRACTS.md', 'docs/SCIENTIFIC_REPORT_1_0.md', 'docs/mission_systems/',
                 'BACKEND_1_0_REPORT.md', 'SCIENTIFIC_REFERENCES.md', 'REMAINING_ISSUES.md', 'VALIDATION_REPORT.md',
                 'BACKEND_FINAL_REPORT.md')
FRONTEND_OWNED = ('web/frontend/', 'desktop/', 'tools/', 'README.md', 'DEMO_SCRIPT.md', 'INTEGRATION_REPORT.md',
                  'WINDOWS_BUILD_REPORT.md', 'FRONTEND_FINAL_REPORT.md', 'DESKTOP_RELEASE_REPORT.md', 'FRONTEND_TEST_RESULTS.md',
                  'FRONTEND_BACKEND_REQUESTS.md', 'FINAL_RELEASE_CHECKLIST.md', 'SUBMISSION_PACK.md', 'BUILD_WINDOWS.bat',
                  'START_AETHER.bat', 'OPEN_DEMO_NO_INSTALL.bat', 'start-offline.bat', 'start-offline.sh', 'start-web-backend.bat',
                  'start-web-frontend.bat', 'RUN_AETHER.py', 'launch_aether.py', 'docs/')
# docs/ is frontend-owned EXCEPT the backend documents above (checked first).
IGNORED_PARTS = {'__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv', '.mypy_cache', 'target', 'dist-windows', '.git'}
IGNORED_SUFFIXES = ('.pyc', '.pyo')
PROJECT_DIR = 'AETHER'


class MergeError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def owner_of(rel: str) -> str | None:
    if any(rel == p or (p.endswith('/') and rel.startswith(p)) for p in BACKEND_OWNED):
        return 'backend'
    if any(rel == p or (p.endswith('/') and rel.startswith(p)) for p in FRONTEND_OWNED):
        return 'frontend'
    return None


def safe_entries(zf: zipfile.ZipFile, label: str) -> list[tuple[zipfile.ZipInfo, str]]:
    """Validate every entry; return (info, project-relative POSIX path) for files. Strips a leading AETHER/ folder."""
    out, seen = [], set()
    for info in zf.infolist():
        name = info.filename.replace('\\', '/')
        if name.startswith('/') or (len(name) > 1 and name[1] == ':') or '\x00' in name:
            raise MergeError(3, f'{label}: absolute path rejected: {info.filename!r}')
        parts = PurePosixPath(name).parts
        if any(p == '..' for p in parts):
            raise MergeError(3, f'{label}: path traversal rejected: {info.filename!r}')
        mode = (info.external_attr >> 16) & 0o177777
        if stat.S_ISLNK(mode):
            raise MergeError(3, f'{label}: symbolic link rejected: {info.filename!r}')
        if info.is_dir():
            continue
        rel = '/'.join(parts[1:]) if parts and parts[0] == PROJECT_DIR else '/'.join(parts)
        if not rel:
            continue
        if rel in seen:
            raise MergeError(3, f'{label}: duplicate entry {rel!r}')
        seen.add(rel)
        out.append((info, rel))
    return out


def ignored(rel: str) -> bool:
    return any(p in IGNORED_PARTS for p in rel.split('/')) or rel.endswith(IGNORED_SUFFIXES)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def read_patch(path: Path, label: str, expect: str) -> tuple[dict[str, bytes], list[str]]:
    files, skipped = {}, []
    with zipfile.ZipFile(path) as zf:
        for info, rel in safe_entries(zf, label):
            if ignored(rel):
                skipped.append(rel)
                continue
            own = owner_of(rel)
            if own != expect:
                raise MergeError(4, f'{label}: {rel!r} is owned by {own or "nobody (shared/unlisted path)"}, not by the {expect} patch')
            files[rel] = zf.read(info)
    return files, skipped


def merge(original: Path, backend: Path, frontend: Path, out: Path, report: Path, allow_identical: bool = False) -> dict:
    for p in (original, backend, frontend):
        if not p.is_file():
            raise MergeError(2, f'missing archive: {p}')
    be, be_skip = read_patch(backend, 'backend patch', 'backend')
    fe, fe_skip = read_patch(frontend, 'frontend patch', 'frontend')
    overlap = sorted(set(be) & set(fe))
    conflicts = [f for f in overlap if not (allow_identical and be[f] == fe[f])]
    if conflicts:
        raise MergeError(5, 'both patches change the same file(s): ' + ', '.join(conflicts))
    with tempfile.TemporaryDirectory(prefix='aether-merge-') as tmp:
        root = Path(tmp) / PROJECT_DIR
        root.mkdir()
        orig_files = {}
        with zipfile.ZipFile(original) as zf:
            for info, rel in safe_entries(zf, 'original archive'):
                dest = (root / rel).resolve()
                if not str(dest).startswith(str(root.resolve()) + '/') and dest != root.resolve():
                    raise MergeError(3, f'original archive: entry escapes the project: {rel!r}')
                dest.parent.mkdir(parents=True, exist_ok=True)
                data = zf.read(info)
                dest.write_bytes(data)
                orig_files[rel] = sha(data)
        changes = []
        for label, files in (('backend', be), ('frontend', fe)):
            for rel, data in sorted(files.items()):
                dest = root / rel
                kind = 'modified' if rel in orig_files else 'added'
                if kind == 'modified' and orig_files[rel] == sha(data):
                    kind = 'unchanged'
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                changes.append((label, kind, rel))
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_zip = out.with_suffix('.zip.partial')
        with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(root.rglob('*')):
                if f.is_file():
                    zf.write(f, f'{PROJECT_DIR}/{f.relative_to(root).as_posix()}')
        shutil.move(tmp_zip, out)
        total = sum(1 for f in root.rglob('*') if f.is_file())
    summary = {'original_files': len(orig_files), 'merged_files': total, 'backend_files': len(be), 'frontend_files': len(fe),
               'identical_overlap': overlap, 'changes': changes, 'skipped': be_skip + fe_skip}
    write_report(report, original, backend, frontend, out, summary)
    return summary


def write_report(report: Path, original: Path, backend: Path, frontend: Path, out: Path, s: dict):
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    lines = [f'# AETHER 1.0 FINAL – merge report', '', f'Generated {now} by `tools/merge_final.py`.', '',
             '| Input | File |', '|---|---|', f'| original | `{original.name}` |', f'| backend patch | `{backend.name}` |',
             f'| frontend patch | `{frontend.name}` |', f'| **output** | `{out.name}` |', '',
             f"Original files: {s['original_files']} · merged files: {s['merged_files']} · backend patch: {s['backend_files']} · "
             f"frontend patch: {s['frontend_files']} · no file was deleted.", '',
             '> **Not tested.** This script only merges files. Run the checks below on the merged tree before calling it a release.', '',
             '```', 'cd AETHER/web/backend && python -m pytest -q tests',
             'cd AETHER/web/frontend && npm install && npm run typecheck && npm test && npm run build:offline -- --mode live --api "" --out dist-offline',
             'node tests/browser/e2e-v10.mjs http://127.0.0.1:8000/   # with the backend serving dist-offline', '```', '', '## Changes', '',
             '| Owner | Change | Path |', '|---|---|---|']
    lines += [f'| {o} | {k} | `{p}` |' for o, k, p in s['changes']]
    if s['identical_overlap']:
        lines += ['', 'Identical files present in both patches (accepted with --allow-identical): ' + ', '.join(f'`{x}`' for x in s['identical_overlap'])]
    if s['skipped']:
        lines += ['', f"## Ignored generated files ({len(s['skipped'])})", ''] + [f'- `{x}`' for x in s['skipped'][:200]]
    report.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('original', type=Path, help='AETHER_1_0_BACKEND.zip (complete original project)')
    ap.add_argument('backend_patch', type=Path, help='AETHER_FINAL_BACKEND_PATCH.zip')
    ap.add_argument('frontend_patch', type=Path, help='AETHER_FINAL_FRONTEND_PATCH.zip')
    ap.add_argument('--out', type=Path, default=Path('AETHER_1_0_FINAL_MERGED.zip'))
    ap.add_argument('--report', type=Path, default=Path('MERGE_REPORT.md'))
    ap.add_argument('--allow-identical', action='store_true', help='accept a file present in both patches if the bytes are identical')
    a = ap.parse_args(argv)
    try:
        s = merge(a.original, a.backend_patch, a.frontend_patch, a.out, a.report, a.allow_identical)
    except MergeError as e:
        print(f'MERGE FAILED ({e.code}): {e}', file=sys.stderr)
        return e.code
    except zipfile.BadZipFile as e:
        print(f'MERGE FAILED (3): not a valid ZIP archive: {e}', file=sys.stderr)
        return 3
    print(f"merged → {a.out}  ({s['merged_files']} files; backend {s['backend_files']}, frontend {s['frontend_files']}; report {a.report})")
    print('NOTE: no tests were run on the merged project – see the report.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
