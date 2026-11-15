"""Tests for tools/merge_final.py:  python -m pytest -q tools/test_merge_final.py"""
import stat
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_final as m  # noqa: E402


def mkzip(path: Path, files: dict, symlink: str | None = None):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, '/etc/passwd')
    return path


@pytest.fixture()
def base(tmp_path):
    orig = mkzip(tmp_path / 'orig.zip', {'AETHER/web/backend/app/a.py': 'a=1', 'AETHER/web/frontend/src/x.ts': 'x', 'AETHER/README.md': 'r',
                                         'AETHER/keep/untouched.txt': 'keep'})
    return tmp_path, orig


def test_successful_merge_keeps_everything(base):
    tmp, orig = base
    be = mkzip(tmp / 'be.zip', {'AETHER/web/backend/app/a.py': 'a=2', 'web/backend/app/__pycache__/a.pyc': 'junk'})
    fe = mkzip(tmp / 'fe.zip', {'web/frontend/src/x.ts': 'y', 'FRONTEND_FINAL_REPORT.md': 'f', 'tools/merge_final.py': '#'})
    out = tmp / 'merged.zip'
    s = m.merge(orig, be, fe, out, tmp / 'r.md')
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert z.read('AETHER/web/backend/app/a.py') == b'a=2' and z.read('AETHER/web/frontend/src/x.ts') == b'y'
        assert 'AETHER/keep/untouched.txt' in names and 'AETHER/FRONTEND_FINAL_REPORT.md' in names
        assert not any('__pycache__' in n for n in names)
    assert s['merged_files'] == 6 and 'Not tested' in (tmp / 'r.md').read_text()


@pytest.mark.parametrize('bad', ['../evil.txt', 'AETHER/../../evil.txt', '/etc/evil', 'C:/evil.txt'])
def test_zip_slip_rejected(base, bad):
    tmp, orig = base
    fe = mkzip(tmp / 'fe.zip', {bad: 'x'})
    be = mkzip(tmp / 'be.zip', {})
    with pytest.raises(m.MergeError) as e:
        m.merge(orig, be, fe, tmp / 'o.zip', tmp / 'r.md')
    assert e.value.code == 3 and not (tmp.parent / 'evil.txt').exists()


def test_symlink_rejected(base):
    tmp, orig = base
    fe = mkzip(tmp / 'fe.zip', {}, symlink='web/frontend/link')
    with pytest.raises(m.MergeError) as e:
        m.merge(orig, mkzip(tmp / 'be.zip', {}), fe, tmp / 'o.zip', tmp / 'r.md')
    assert e.value.code == 3


@pytest.mark.parametrize('patch,path', [('frontend', 'web/backend/app/a.py'), ('backend', 'web/frontend/src/x.ts'),
                                        ('frontend', 'docs/API_CONTRACTS.md'), ('backend', 'random/file.txt')])
def test_ownership_enforced(base, patch, path):
    tmp, orig = base
    files = {path: 'x'}
    be = mkzip(tmp / 'be.zip', files if patch == 'backend' else {})
    fe = mkzip(tmp / 'fe.zip', files if patch == 'frontend' else {})
    with pytest.raises(m.MergeError) as e:
        m.merge(orig, be, fe, tmp / 'o.zip', tmp / 'r.md')
    assert e.value.code == 4


def test_overlap_refused_unless_identical(base, monkeypatch):
    tmp, orig = base
    monkeypatch.setattr(m, 'FRONTEND_OWNED', m.FRONTEND_OWNED + ('shared.txt',))
    monkeypatch.setattr(m, 'BACKEND_OWNED', m.BACKEND_OWNED + ('shared.txt',))
    # owner_of returns 'backend' first, so simulate the overlap through a path both patches legitimately carry
    monkeypatch.setattr(m, 'owner_of', lambda rel: 'backend' if 'be' in str(rel) else None)
    be = {'shared.txt': b'1'}; fe = {'shared.txt': b'2'}
    monkeypatch.setattr(m, 'read_patch', lambda p, label, expect: (be if expect == 'backend' else fe, []))
    with pytest.raises(m.MergeError) as e:
        m.merge(orig, orig, orig, tmp / 'o.zip', tmp / 'r.md')
    assert e.value.code == 5
    fe['shared.txt'] = b'1'
    m.merge(orig, orig, orig, tmp / 'o.zip', tmp / 'r.md', allow_identical=True)


def test_cli_missing_archive(tmp_path, capsys):
    assert m.main([str(tmp_path / 'nope.zip'), str(tmp_path / 'a.zip'), str(tmp_path / 'b.zip')]) == 2
    assert 'MERGE FAILED' in capsys.readouterr().err
