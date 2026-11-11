import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
if ROOT.name != "dioramic":
    raise RuntimeError("run tests from a checkout directory named 'dioramic'")
