import os
import sys
import warnings
from pathlib import Path

# Ignore warnings from app.shared
warnings.filterwarnings("ignore", category=DeprecationWarning, module="app.shared.*")

# Set test environment variables
os.environ.update({})

# Ensure `app` directory is on sys.path so `app` packages resolve
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
app_dir_str = str(APP_DIR)
if app_dir_str not in sys.path:
    sys.path.insert(0, app_dir_str)

# Import database fixtures so they are available to all tests
from tests.fixtures.mongo_fixtures import *  # noqa: E402, F403
from tests.fixtures.postgres_fixtures import *  # noqa: E402, F403
