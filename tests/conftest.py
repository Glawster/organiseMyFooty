"""Pytest configuration for source imports and logUtils stubs."""

import sys
import types
from pathlib import Path


class _FakeStructuredLogger:
    """Test stub for organiseMyProjects.logUtils logger instances."""

    def __init__(self, name: str = "test.logger", **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.messages: list[tuple[str, tuple, dict]] = []

    def _record(self, level: str, *args, **kwargs):
        self.messages.append((level, args, kwargs))

    def info(self, *args, **kwargs):
        self._record("info", *args, **kwargs)

    def warning(self, *args, **kwargs):
        self._record("warning", *args, **kwargs)

    def debug(self, *args, **kwargs):
        self._record("debug", *args, **kwargs)

    def error(self, *args, **kwargs):
        self._record("error", *args, **kwargs)

    def action(self, *args, **kwargs):
        self._record("action", *args, **kwargs)

    def doing(self, *args, **kwargs):
        self._record("doing", *args, **kwargs)

    def done(self, *args, **kwargs):
        self._record("done", *args, **kwargs)

    def value(self, *args, **kwargs):
        self._record("value", *args, **kwargs)


def _fake_get_logger(name: str = "test.logger", **kwargs):
    """Return a stub logger matching the organiseMyProjects.logUtils factory."""
    return _FakeStructuredLogger(name, **kwargs)


def _fake_draw_box(*_args, **_kwargs):
    """Ignore drawBox output in unit tests."""
    return None


_stubbed_organiseMyProjects = types.ModuleType("organiseMyProjects")
_stubbed_logUtils = types.ModuleType("organiseMyProjects.logUtils")
setattr(_stubbed_logUtils, "getLogger", _fake_get_logger)
setattr(_stubbed_logUtils, "drawBox", _fake_draw_box)
setattr(_stubbed_organiseMyProjects, "logUtils", _stubbed_logUtils)
sys.modules.setdefault("organiseMyProjects", _stubbed_organiseMyProjects)
sys.modules.setdefault("organiseMyProjects.logUtils", _stubbed_logUtils)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
