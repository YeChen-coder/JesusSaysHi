"""Write/refresh the 'jesus' entry in avatar/characters.json from the packaged release.json (host Python).

usage: python register_character.py [asset_dir] [--reference N]
--reference N fixes the model reference to unique idle frame N (default: follow the moving base)
Paths in the entry are relative to the mounted asset folder (JESUS_AVATAR_ASSETS).
The default character is left unchanged.
"""
import json
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
args = sys.argv[1:]
reference = None
if '--reference' in args:
    k = args.index('--reference')
    reference = int(args[k + 1])
    del args[k:k + 2]
package = Path(args[0]) if args else here.parent / 'avatar_assets' / 'jesus_20261021'
release = json.loads((package / 'release.json').read_text(encoding='utf-8'))
files = release['files']
checkpoint = next(k for k in files if k.startswith('checkpoints/'))
catalog_path = here.parent / 'avatar' / 'characters.json'
catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
entry = {
    'release': f"20261021-muse-epoch{release['epoch']}-{release['idle']}",
    'selected_epoch': release['epoch'],
    'idle_name': release['idle'],
    'checkpoint_sha256': files[checkpoint],
    'idle_video_sha256': files['data/loop_base/idle.mp4'],
    'checkpoint': checkpoint,
    'base': 'data/loop_base',
    'image': 'data/base.jpg',
    'landmarks': 'data/base.lms',
    'renderer': 'native_face',
    'runtime_mode': 'stream80',
    'settings': {'teeth_mode': 'model', 'detail_profile': 'original', 'settle_ms': 0},
}
if reference is not None:
    entry['settings']['model_reference_frame'] = reference
catalog['characters']['jesus'] = entry
catalog['_comment'] = ("gentleman is the SpecterSaysHi placeholder. jesus = Muse-trained model (2026-10-21); "
                       "run it with JESUS_AVATAR_CHARACTER=jesus, JESUS_AVATAR_MODE=stream80 and "
                       "JESUS_AVATAR_ASSETS pointing at avatar_assets/jesus_20261021.")
catalog_path.write_text(json.dumps(catalog, indent=2) + '\n', encoding='utf-8')
print(json.dumps(catalog['characters']['jesus'], indent=2))
