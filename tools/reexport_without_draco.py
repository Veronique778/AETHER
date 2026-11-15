"""Re-export a Draco-compressed GLB without mesh compression so AETHER's built-in WebGL loader can read it.

skeleton.glb from the 3D team uses KHR_draco_mesh_compression (required extension). AETHER's dependency-free
GLB reader (web/frontend/src/scene3d/glb.ts) does not include a Draco decoder, so the BODY "Skeleton" model
reports this honestly and falls back to the schematic figure. Blender decodes Draco on import, so a plain
re-export fixes it:

    blender --background --python tools/reexport_without_draco.py -- web/frontend/public/models/skeleton.glb

The file is overwritten in place (a .draco.bak copy is kept). Then rebuild the UI (npm run build:offline /
BUILD_WINDOWS.bat). Requires Blender 3.6+ (glTF importer with Draco support is bundled).
"""
import shutil
import sys
from pathlib import Path

import bpy  # noqa: provided by Blender

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if not args:
    raise SystemExit('usage: blender --background --python reexport_without_draco.py -- <file.glb> [out.glb]')
src = Path(args[0]).resolve()
dst = Path(args[1]).resolve() if len(args) > 1 else src
if dst == src:
    shutil.copy2(src, src.with_suffix('.draco.bak'))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(src))
bpy.ops.export_scene.gltf(filepath=str(dst), export_format='GLB', export_draco_mesh_compression_enable=False,
                          export_apply=True, export_yup=True)
print(f'Re-exported without Draco: {dst}')
