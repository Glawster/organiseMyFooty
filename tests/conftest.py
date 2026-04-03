"""Pytest configuration: add src/ to sys.path so test modules can import source files."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
