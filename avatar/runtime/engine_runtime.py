"""One model and lock owned only by the avatar server."""
import threading
import sys
# Script directory /lab precedes PYTHONPATH; select the new engine explicitly.
sys.path.insert(0, '/engine')
from character_assets import character_assets

profile=character_assets()
if profile.renderer=='native_face':
    from native_loop_core import NativeLoopEngine
    engine=NativeLoopEngine()
elif profile.renderer=='legacy_detail':
    from loop_core import LoopEngine
    engine=LoopEngine()
else:
    raise ValueError('Unknown character rendering profile')
lock=threading.Lock()
