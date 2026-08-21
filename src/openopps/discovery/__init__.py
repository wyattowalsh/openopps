"""Bounded, quarantined source-discovery contracts.

The discovery package is deliberately independent from operational storage,
runtime caches, plugin loading, and CLI wiring.  Its modules expose strict,
deterministic primitives that can be reused by an isolated scout process and
offline verification commands.
"""

from __future__ import annotations


__all__: tuple[str, ...] = ()
