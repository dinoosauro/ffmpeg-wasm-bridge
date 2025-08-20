import shutil
import os
from pathlib import Path
def get_cache_dir():
    """Get platform-appropriate cache directory"""
    if os.name == 'nt':  # Windows
        cache_dir = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:  # Unix-like
        cache_dir = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    
    return cache_dir / 'ffmpeg-wasm-bridge'

shutil.rmtree(get_cache_dir())