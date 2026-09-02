from __future__ import annotations

import re

CONTACT_NAME_MARKER = "HWFC"


def stripContactNameMarker(name: str, marker: str = CONTACT_NAME_MARKER) -> str:
    """Remove a trailing contact-only marker without changing genuine name text."""
    value = " ".join(name.split()).strip()
    markerValue = " ".join(marker.split()).strip()
    if not value or not markerValue:
        return value

    return re.sub(
        rf"\s+{re.escape(markerValue)}$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
