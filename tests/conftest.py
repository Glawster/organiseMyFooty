"""Pytest configuration for source imports and logUtils stubs."""

import sys
import types
from pathlib import Path


class _FakeStructuredLogger:
    """Test stub for organiseMyProjects.logUtils logger instances."""

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
    """Return a stub logger matching the organiseMyProjects.logUtils factory."""
    return _FakeStructuredLogger(name, **kwargs)


_stubbed_organiseMyProjects = types.ModuleType("organiseMyProjects")
_stubbed_logUtils = types.ModuleType("organiseMyProjects.logUtils")
_stubbed_logUtils.getLogger = _fake_get_logger
_stubbed_organiseMyProjects.logUtils = _stubbed_logUtils
sys.modules.setdefault("organiseMyProjects", _stubbed_organiseMyProjects)
sys.modules.setdefault("organiseMyProjects.logUtils", _stubbed_logUtils)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
