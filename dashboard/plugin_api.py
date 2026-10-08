"""Desktop/Dashboard backend, mounted at /api/plugins/ne-observability/."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT in sys.path:
    sys.path.remove(_ROOT)
sys.path.insert(0, _ROOT)

import obs_report  # noqa: E402

router = APIRouter()


@router.get("/report")
async def report(days: int = 30, board: str = "") -> dict:
    return obs_report.build(days, board)
