"""Pytest config: force stub mode for every test."""

import os

os.environ.setdefault("GLOWCHART_STUB", "1")
