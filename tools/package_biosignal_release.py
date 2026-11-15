"""Package AETHER 1.1 distributables against the supplied baseline ZIP.
Run from project root; no raw private validation recordings are included.
"""
import os
import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('baseline');p.add_argument('--out',default='../../../AETHER_1_1_DELIVERABLES');a=p.parse_args()
root=Path.cwd().resolve();out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
z=zipfile.ZipFile(a.baseline);prefix='AETHER_1_0_DESKTOP_NO_NODE/AETHER/'
original={n[len(prefix):]:n for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')}
exclude_dirs={'.aether-venv','node_modules','__pycache__','.pytest_cache','.git','build','build-tools'}
exclude_files={'baseline-tests.txt','frontend-install.txt'}
def excluded(path):return bool(set(Path(path).parts)&exclude_dirs) or Path(path).name in exclude_files or path.endswith(('.pyc','.pyo'))
files={}
for directory, dirs, names in os.walk(root):
    dirs[:] = [name for name in dirs if name not in exclude_dirs]
    for name in names:
        file=Path(directory)/name
        rel=file.relative_to(root).as_posix()
        if excluded(rel):continue
        if file.suffix.lower() in ('.sqlite3','.sqlite','.db'):
            if rel in original:files[rel]=z.read(original[rel])
            continue
        files[rel]=file.read_bytes()
changed={name:data for name,data in files.items() if name not in original or hashlib.sha256(data).digest()!=hashlib.sha256(z.read(original[name])).digest()}
asset_names=[n for n in original if n.endswith('.glb')]
assert all(n in files and hashlib.sha256(files[n]).digest()==hashlib.sha256(z.read(original[n])).digest() for n in asset_names)
manifest={'release':'AETHER 1.1 Real Biosignal Intelligence','baseline_zip':Path(a.baseline).name,
          'original_glb_files_preserved':len(asset_names),'files':len(files),'patch_files':len(changed)+1,
          'excluded_original_files':[n for n in original if excluded(n)],
          'exclusions':['machine-specific virtualenvs','node_modules/developer package manager','Python caches','temporary build files','raw private MMASH recordings','generated test databases'],
          'patch_instructions':'Extract AETHER/ into the parent of your existing AETHER folder. Back up data first. A copied free-threaded/broken .aether-venv must be removed or automatically recreated by the launcher.',
          'sha256':{n:hashlib.sha256(data).hexdigest() for n,data in changed.items()}}
content=json.dumps(manifest,indent=2).encode();files['RELEASE_MANIFEST.json']=content;changed['RELEASE_MANIFEST.json']=content
(root/'RELEASE_MANIFEST.json').write_bytes(content)
for name,items,folder in [('AETHER_1_1_REAL_BIOSIGNAL.zip',files,'AETHER_1_1_REAL_BIOSIGNAL/AETHER/'),('AETHER_1_1_PATCH.zip',changed,'AETHER/')]:
    with zipfile.ZipFile(out/name,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for rel,data in sorted(items.items()):archive.writestr(folder+rel,data)
    with zipfile.ZipFile(out/name) as archive:assert archive.testzip() is None
    print(name,(out/name).stat().st_size,flush=True)
# Portable also offered separately so the source archive is not required for running.
portable={n[len('dist/'):]:data for n,data in files.items() if n.startswith('dist/AETHER_1_1_PORTABLE/')}
with zipfile.ZipFile(out/'AETHER_1_1_WINDOWS_PORTABLE.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for rel,data in sorted(portable.items()):archive.writestr(rel,data)
for name in ['BIOSIGNAL_IMPLEMENTATION_REPORT.md','DATASET_VALIDATION_REPORT.md','BLE_INTEGRATION_REPORT.md','BACKEND_TEST_REPORT.md','AETHER_1_1_DEMO.md','RELEASE_CHECKLIST.md','README_AETHER_1_1.md','RELEASE_MANIFEST.json']:
    shutil.copy2(root/name,out/name)
print('Delivery folder:',out)
