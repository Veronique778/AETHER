"""Make a lighter copy of a GLB for the built-in WebGL loader (AETHER 0.9).

* Welds exactly identical vertices (same position, normal, UV bits) and rebuilds indices – geometry is unchanged.
* Re-encodes textures as JPEG (quality configurable) and optionally downsizes them – this step is lossy.
* Leaves materials, node names (used for the muscle-layer lookup) and attribute formats unchanged, so no new
  glTF extension is required. The original file is never modified.

Usage: python tools/optimize_glb.py input.glb output.glb [--max-texture 2048] [--jpeg-quality 88]
"""
from __future__ import annotations

import argparse
import io
import json
import struct

import numpy as np
from PIL import Image

CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def read_glb(path):
    b = open(path, 'rb').read()
    magic, _, _ = struct.unpack('<III', b[:12])
    assert magic == 0x46546C67, 'not a GLB'
    cl, _ = struct.unpack('<II', b[12:20])
    j = json.loads(b[20:20 + cl])
    bl, _ = struct.unpack('<II', b[20 + cl:28 + cl])
    return j, b[28 + cl:28 + cl + bl]


def accessor(j, binb, i):
    a = j['accessors'][i]
    bv = j['bufferViews'][a['bufferView']]
    assert 'byteStride' not in bv or bv['byteStride'] == np.dtype(CT[a['componentType']]).itemsize * NC[a['type']], 'interleaved buffers not supported'
    off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    arr = np.frombuffer(binb, CT[a['componentType']], a['count'] * NC[a['type']], off)
    return arr.reshape(a['count'], NC[a['type']]) if NC[a['type']] > 1 else arr


def optimize(src, dst, max_tex=2048, quality=88):
    j, binb = read_glb(src)
    if j.get('extensionsRequired'):
        raise SystemExit(f"{src} requires {j['extensionsRequired']} – cannot be processed without a decoder")
    out = bytearray()
    views, accs = [], []

    def add_view(data: bytes, target=None):
        while len(out) % 4:
            out.append(0)
        views.append({'buffer': 0, 'byteOffset': len(out), 'byteLength': len(data), **({'target': target} if target else {})})
        out.extend(data)
        return len(views) - 1

    def add_acc(arr, ctype, typ, minmax=False):
        a = {'bufferView': add_view(arr.tobytes(), 34963 if typ == 'SCALAR' else 34962), 'componentType': ctype, 'count': int(len(arr)), 'type': typ}
        if minmax:
            a['min'] = arr.min(0).tolist(); a['max'] = arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    report = []
    for m in j['meshes']:
        for p in m['primitives']:
            names = sorted(p['attributes'])
            cols = {k: accessor(j, binb, p['attributes'][k]) for k in names}
            n = len(cols[names[0]])
            idx = accessor(j, binb, p['indices']).astype(np.uint32) if 'indices' in p else np.arange(n, dtype=np.uint32)
            key = np.concatenate([cols[k].reshape(n, -1).view(np.uint8).reshape(n, -1) for k in names], axis=1)
            _, first, inverse = np.unique(np.ascontiguousarray(key).view(np.dtype((np.void, key.shape[1]))).ravel(), return_index=True, return_inverse=True)
            order = np.argsort(first)                       # keep original vertex order
            remap = np.empty(len(order), np.uint32); remap[order] = np.arange(len(order), dtype=np.uint32)
            new_idx = remap[inverse.ravel()][idx]
            keep = first[order]
            for k in names:
                a = j['accessors'][p['attributes'][k]]
                p['attributes'][k] = add_acc(np.ascontiguousarray(cols[k][keep]), a['componentType'], a['type'], k == 'POSITION')
            ictype = 5123 if len(keep) < 65536 else 5125
            p['indices'] = add_acc(new_idx.astype(np.uint16 if ictype == 5123 else np.uint32), ictype, 'SCALAR')
            report.append((m.get('name'), n, len(keep)))
    for im in j.get('images', []):
        bv = j['bufferViews'][im['bufferView']]
        raw = binb[bv.get('byteOffset', 0):bv.get('byteOffset', 0) + bv['byteLength']]
        img = Image.open(io.BytesIO(raw))
        if img.mode not in ('RGB', 'L'):
            # keep images with alpha as PNG (JPEG has no alpha)
            img.thumbnail((max_tex, max_tex)); buf = io.BytesIO(); img.save(buf, 'PNG', optimize=True); mime = 'image/png'
        else:
            img.thumbnail((max_tex, max_tex)); buf = io.BytesIO(); img.save(buf, 'JPEG', quality=quality, optimize=True); mime = 'image/jpeg'
        im['bufferView'] = add_view(buf.getvalue()); im['mimeType'] = mime
    j['accessors'] = accs + [a for a in []]
    j['bufferViews'] = views
    j['buffers'] = [{'byteLength': len(out)}]
    j.setdefault('asset', {})['generator'] = (j['asset'].get('generator', '') + ' + AETHER optimize_glb.py').strip()
    js = json.dumps(j, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    out += b'\0' * (-len(out) % 4)
    glb = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(out)) + struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(out), 0x004E4942) + bytes(out)
    open(dst, 'wb').write(glb)
    return report


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--max-texture', type=int, default=2048); ap.add_argument('--jpeg-quality', type=int, default=88)
    a = ap.parse_args()
    for name, before, after in optimize(a.src, a.dst, a.max_texture, a.jpeg_quality):
        print(f'{name}: {before} → {after} vertices')
