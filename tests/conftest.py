import sys
from pathlib import Path

# dw_records is a flat module next to the sync scripts it serves, not an
# installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "sync_images"))
