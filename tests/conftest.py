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

    def _recordLog(self, level: str, *args, **kwargs):
        self.messages.append((level, args, kwargs))

    def info(self, *args, **kwargs):
        self._recordLog("info", *args, **kwargs)

    def warning(self, *args, **kwargs):
        self._recordLog("warning", *args, **kwargs)

    def debug(self, *args, **kwargs):
        self._recordLog("debug", *args, **kwargs)

    def error(self, *args, **kwargs):
        self._recordLog("error", *args, **kwargs)

    def action(self, *args, **kwargs):
        self._recordLog("action", *args, **kwargs)

    def doing(self, *args, **kwargs):
        self._recordLog("doing", *args, **kwargs)

    def done(self, *args, **kwargs):
        self._recordLog("done", *args, **kwargs)

    def value(self, *args, **kwargs):
        self._recordLog("value", *args, **kwargs)

    def hasMessage(self, level: str, message: str) -> bool:
        return any(
            entryLevel == level and message in args[0]
            for entryLevel, args, _kwargs in self.messages
            if args and isinstance(args[0], str)
        )

    def hasCall(self, level: str, message: str, *callArgs) -> bool:
        return any(
            entryLevel == level and args == (message, *callArgs)
            for entryLevel, args, _kwargs in self.messages
        )


def _fakeGetLogger(name: str = "test.logger", **kwargs):
    """Return a stub logger matching the organiseMyProjects.logUtils factory."""
    return _FakeStructuredLogger(name, **kwargs)


def _fakeDrawBox(*_args, **_kwargs):
    """Ignore drawBox output in unit tests."""
    return None


def _fakeSetApplication(*_args, **_kwargs):
    """Ignore application logger setup in unit tests."""
    return None


_stubbedOrganiseMyProjects = types.ModuleType("organiseMyProjects")
_stubbedLogUtils = types.ModuleType("organiseMyProjects.logUtils")
setattr(_stubbedLogUtils, "getLogger", _fakeGetLogger)
setattr(_stubbedLogUtils, "drawBox", _fakeDrawBox)
setattr(_stubbedLogUtils, "setApplication", _fakeSetApplication)
setattr(_stubbedOrganiseMyProjects, "logUtils", _stubbedLogUtils)
sys.modules.setdefault("organiseMyProjects", _stubbedOrganiseMyProjects)
sys.modules.setdefault("organiseMyProjects.logUtils", _stubbedLogUtils)

_repoRoot = Path(__file__).parent.parent
sys.path.insert(0, str(_repoRoot))
sys.path.insert(0, str(_repoRoot / "src"))
