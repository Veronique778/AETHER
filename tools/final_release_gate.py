#!/usr/bin/env python3
"""Checks that a native archive exists, carries a recent AETHER frontend and passes smoke.
Does NOT certify GUI, physical Bluetooth, clinical validity, or other platforms.
"""
import argparse, hashlib, json, os, tarfile, zipfile
from pathlib import Path

LATEST_MARKERS = (
    b'Your measurements on the 3D human model',
    b'Scan HRS monitors',
    b'Personal Monitoring',
)
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--platform', required=True, choices=['windows','macos','linux'])
    p.add_argument('--archive', required=True)
    p.add_argument('--smoke', required=True)
    p.add_argument('--ble')
    a = p.parse_args()
    archive=Path(a.archive)
    assert archive.is_file(), f'Missing release archive: {archive}'
    smoke=json.loads(Path(a.smoke).read_text(encoding='utf-8'))
    assert str(smoke.get('status','')).lower()=='pass', f'Smoke did not PASS: {smoke.get("status")}'
    assert smoke.get('failed',0)==0, f'Smoke has failed checks: {smoke.get("failed")}'
    files={}
    if archive.suffix=='.zip':
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None, 'Corrupt zip'
            n=z.namelist()
            for name in n:
                if name.endswith('BUILD_INFO.json') or name.endswith('.js') or name.endswith('.exe') or name.endswith('/AETHER') or name.endswith('.app/Contents/MacOS/AETHER'):
                    if name.endswith('.js') or name.endswith('BUILD_INFO.json'):
                        files[name]=z.read(name)
                    else: files[name]=b''
    else:
        with tarfile.open(archive,'r:gz') as t:
            n=t.getnames()
            for member in t:
                name=member.name
                if name.endswith('BUILD_INFO.json') or name.endswith('.js') or name.endswith('/AETHER'):
                    if member.isfile():
                        if name.endswith('.js') or name.endswith('BUILD_INFO.json'):
                            f=t.extractfile(member); files[name]=f.read() if f else b''
                        else: files[name]=b''
    names=list(files)
    if a.platform=='windows':
        assert any(x.endswith('/AETHER_1_5.exe') for x in names), 'Missing Windows exe'
    elif a.platform=='macos':
        assert any('AETHER.app/Contents/MacOS/AETHER' in x or x.endswith('/AETHER') for x in names), 'Missing macOS app/exec'
    else:
        assert any(x.endswith('/AETHER') for x in names), 'Missing Linux executable'
    info_files=[x for x in names if x.endswith('BUILD_INFO.json') and '/frontend/dist/' in x]
    assert info_files, 'Frontend BUILD_INFO.json missing in native package'
    info=json.loads(files[info_files[0]].decode())
    assert len(str(info.get('source_sha256',''))) == 64, 'Frontend source hash missing'
    js=b'\n'.join(val for name,val in files.items() if name.endswith('.js') and '/frontend/dist/' in name)
    missing=[m.decode() for m in LATEST_MARKERS if m not in js]
    assert not missing, f'Old React frontend! Missing latest code markers: {missing}'
    if a.platform=='windows':
        assert a.ble and Path(a.ble).is_file(), 'Missing frozen BLE diagnostics report'
        ble=json.loads(Path(a.ble).read_text(encoding='utf-8'))
        imports=ble.get('imports',{})
        assert imports and all(v=='ok' for v in imports.values()), f'BLE imports failed: {imports}'
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    output={'archive':str(archive),'platform':a.platform,'archive_sha256':digest,
            'smoke_passed':smoke.get('passed'),'smoke_failed':smoke.get('failed'),
            'frontend_source_sha256':info.get('source_sha256'),
            'status':'SOFTWARE_RELEASE_CANDIDATE',
            'not_tested':['GUI manual interactions','real physical BLE device','clinical validation','clean external PC']}
    path=archive.with_suffix(archive.suffix+'.verification.json')
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':
    raise SystemExit(main())
