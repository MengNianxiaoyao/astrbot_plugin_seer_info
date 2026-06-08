"""
Seer Data module for AstrBot plugin.

Provides database and image dependencies for SeerInfo plugin.
"""

from . import db, image  # noqa: F401

__all__ = ["db", "image"]
