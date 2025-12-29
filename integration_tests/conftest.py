"""Pytest configuration for integration tests.

Integration tests interact with real external services (Mux, LiveKit, etc.)
and require actual credentials to run.
"""

import sys
import warnings
from pathlib import Path

# Ignore warnings from app.cw
warnings.filterwarnings("ignore", category=DeprecationWarning, module="app.cw.*")

# Ensure `app` directory is on sys.path so `cw` and `app` packages resolve
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
app_dir_str = str(APP_DIR)
if app_dir_str not in sys.path:
    sys.path.insert(0, app_dir_str)
