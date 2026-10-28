"""Compatibility entrypoint. The maintained browser suite targets v0.6."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name('browser_v06.py')),run_name='__main__')
