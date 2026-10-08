"""ne-observability: local, per-profile observability for Hermes (skills, subagents, approvals,
permission issues, aux-model usage) plus token/model rollups across every profile."""

from __future__ import annotations

import sys
from pathlib import Path

_DIR = str(Path(__file__).resolve().parent)
if _DIR in sys.path:
    sys.path.remove(_DIR)
sys.path.insert(0, _DIR)

import obs_hooks  # noqa: E402
import obs_report  # noqa: E402


def _handle_slash(raw_args: str) -> str:
    parts = (raw_args or "").strip().split()
    if parts and parts[0].lower() in {"help", "?"}:
        return "Usage: /obs [days]   e.g. /obs 7. Full view: Observability page in Desktop."
    days = 30
    if parts:
        try:
            days = int(parts[0])
        except ValueError:
            pass
    try:
        return obs_report.markdown(obs_report.build(days), top=8)
    except Exception as exc:  # pragma: no cover
        return f"(observability report failed: {type(exc).__name__})"


def register(ctx) -> None:
    for hook_name, fn in obs_hooks.HOOKS.items():
        ctx.register_hook(hook_name, fn)
    try:
        ctx.register_command("obs", handler=_handle_slash,
                             description="Observability: tokens, aux share, skills, subagents, permissions",
                             args_hint="[days]")
    except TypeError:
        ctx.register_command("obs", handler=_handle_slash,
                             description="Observability: tokens, aux share, skills, subagents, permissions")
    except Exception:
        pass
