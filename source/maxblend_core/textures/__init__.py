# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Wave 1 F4: offline, Blender-independent texture lookup and graph intent."""
from .graph import BitmapSource, TextureGraphResult, extract_bitmap_sources, resolve_graph
from .resolver import ResolutionDetail, SafeTextureResolver, classify_channel

__all__ = ["BitmapSource", "TextureGraphResult", "ResolutionDetail", "SafeTextureResolver",
           "classify_channel", "extract_bitmap_sources", "resolve_graph"]
