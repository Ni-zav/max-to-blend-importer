# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline defensive MAX preflight; does not authorize calling legacy parser."""
from .chunks import UnsafeContainer, decompress_limited, validate_chunks
from .probe import DefensiveContainerProbe, ProbeLimits, ProbeSummary

__all__ = ["UnsafeContainer", "decompress_limited", "validate_chunks",
           "DefensiveContainerProbe", "ProbeLimits", "ProbeSummary"]