"""Pytest configuration for source imports and logUtils stubs."""

import sys
import types
from pathlib import Path


class _FakeStructuredLogger:
    def __init__(self, name: str, **kwargs):
        self.name = name
        self.kwargs = kwargs

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def action(self, *args, **kwargs):
        return None

    def doing(self, *args, **kwargs):
        return None

    def done(self, *args, **kwargs):
        return None

    def value(self, *args, **kwargs):
        return None


def _fake_get_logger(name: str, **kwargs):
    return _FakeStructuredLogger(name, **kwargs)


organiseMyProjects = types.ModuleType("organiseMyProjects")
logUtils = types.ModuleType("organiseMyProjects.logUtils")
logUtils.getLogger = _fake_get_logger
logUtils.thisApplication = "organiseMyFooty"
organiseMyProjects.logUtils = logUtils
sys.modules.setdefault("organiseMyProjects", organiseMyProjects)
sys.modules.setdefault("organiseMyProjects.logUtils", logUtils)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
