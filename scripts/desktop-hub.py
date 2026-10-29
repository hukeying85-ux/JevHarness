#!/usr/bin/env python3
"""Standalone CLI entry point for the JevHarness Desktop Hub bridge."""
from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from auto_jev.desktop_hub import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
