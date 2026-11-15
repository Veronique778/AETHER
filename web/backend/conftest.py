"""Makes `app` and `mission_systems` importable when pytest is started from any directory (1.4)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
