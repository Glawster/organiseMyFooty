"""Pytest configuration for source imports and logUtils stubs."""

import sys
import types
from pathlib import Path


class _FakeStructuredLogger:
    def __init__(self, name: str, **kwargs):
        self.name = name
        self.kwargs = kwargs

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def action(self, *args, **kwargs):
        pass

    def doing(self, *args, **kwargs):
        pass

    def done(self, *args, **kwargs):
        pass

    def value(self, *args, **kwargs):
        pass


def _fake_get_logger(name: str, **kwargs):
    return _FakeStructuredLogger(name, **kwargs)


organiseMyProjects = types.ModuleType("organiseMyProjects")
logUtils = types.ModuleType("organiseMyProjects.logUtils")
logUtils.getLogger = _fake_get_logger
organiseMyProjects.logUtils = logUtils
sys.modules.setdefault("organiseMyProjects", organiseMyProjects)
sys.modules.setdefault("organiseMyProjects.logUtils", logUtils)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
