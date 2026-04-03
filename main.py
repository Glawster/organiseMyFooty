from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from exportAttendance import main as run_app  # noqa: E402

if __name__ == "__main__":
    run_app()
