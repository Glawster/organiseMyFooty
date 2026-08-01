import os
import re
import string
from datetime import datetime, timedelta

# globalVars.py

"""
Centralized configuration and constants for the Organise My ... application.
"""

# Application Info
APPLICATION = "Organise My ..."
VERSION = "1.0"

# File Paths
CREDENTIALS_FILE = ".icloud_credentials.json"
KEY_FILE = ".icloud_key"
LOG_FILE = "icloudSync.log"

# Security Settings
ENABLE_2FA = True
USE_ENCRYPTION = True

# UI Defaults
WINDOW_WIDTH = 300
WINDOW_HEIGHT = 400

# Debugging
DEBUG_MODE = False

PAD_X = 10
PAD_Y = 10
PAD_Y_TOP = (10, 0)
PAD_X_LEFT = (0, 5)


def getAppTitle(subtitle: str = None) -> str:
    """Generate consistent window title text."""
    return f"{APPLICATION}... {subtitle}" if subtitle else APPLICATION


def getCredentialPaths() -> tuple:
    """Return paths for the credentials and key file."""
    return CREDENTIALS_FILE, KEY_FILE


def isDebugMode() -> bool:
    """Check if debug mode is enabled."""
    return DEBUG_MODE


def use2fa() -> bool:
    """Check if 2FA should be enabled."""
    return ENABLE_2FA
