"""Observer hooks. Metadata only: no prompts, args, results, or commands are stored. Never raise."""

from __future__ import annotations

import re
from typing import Any

import obs_store

# Error text that means "the agent was not allowed", as opposed to "the thing broke".
_PERM_RE = re.compile(
    r"permission denied|access is denied|access denied|operation not permitted|not permitted|"
    r"\beacces\b|\beperm\b|\b401\b|\b403\b|forbidden|unauthori[sz]ed|insufficient[_ ](scope|permission)|"
    r"requires approval|blocked by (policy|hook|guard)|not allowed",
    re.IGNORECASE,
)
_DENY_CHOICES = {"deny", "denied", "timeout", "cancelled", "canceled", "reject", "rejected"}


def _snippet(text: Any, limit: int = 240) -> str:
    s = str(text or "")
    try:
        from agent.redact import redact_sensitive_text

        s = redact_sensitive_text(s, force=True)
    except Exception:
        pass
    return s[:limit]


def _is_perm_text(text: Any) -> bool:
    return bool(text) and bool(_PERM_RE.search(str(text)))


# --- skills ---------------------------------------------------------------
def on_skill_lifecycle(**kw: Any) -> None:
    try:
        action = str(kw.get("action") or "")
        obs_store.record(
            "skill", name=kw.get("skill_name"), status=action,
            session_id=kw.get("session_id"), task_id=kw.get("task_id"),
            detail={"provenance": kw.get("provenance"), "use_count": kw.get("use_count"),
                    "reused": kw.get("reused")},
        )
    except Exception:
        return


# --- subagents ------------------------------------------------------------
def on_subagent_start(**kw: Any) -> None:
    try:
        obs_store.record(
            "subagent_start", name=kw.get("child_role") or "subagent", status="started",
            session_id=kw.get("parent_session_id"),
            detail={"child_session_id": kw.get("child_session_id"),
                    "goal": _snippet(kw.get("child_goal"), 160)},
        )
    except Exception:
        return


def on_subagent_stop(**kw: Any) -> None:
    try:
        history = kw.get("tool_call_history") or []
        obs_store.record(
            "subagent_stop", name=kw.get("child_role") or "subagent", status=kw.get("child_status"),
            session_id=kw.get("parent_session_id"), duration_ms=kw.get("duration_ms"),
            detail={"child_session_id": kw.get("child_session_id"),
                    "tool_calls": len(history) if isinstance(history, list) else None},
        )
    except Exception:
        return


# --- approvals ------------------------------------------------------------
def on_pre_approval_request(**kw: Any) -> None:
    try:
        obs_store.record(
            "approval_request", name=kw.get("pattern_key") or "approval", status="requested",
            session_id=kw.get("session_id"),
            detail={"surface": kw.get("surface") or kw.get("platform"),
                    "description": _snippet(kw.get("description"), 160)},
        )
    except Exception:
        return


def on_post_approval_response(**kw: Any) -> None:
    try:
        choice = str(kw.get("choice") or "").lower()
        obs_store.record(
            "approval_response", name=kw.get("pattern_key") or "approval", status=choice or "unknown",
            perm=choice in _DENY_CHOICES, session_id=kw.get("session_id"),
            detail={"decided_by": kw.get("decided_by"), "surface": kw.get("surface")},
        )
    except Exception:
        return


# --- tools (only non-ok outcomes are stored) -------------------------------
def on_post_tool_call(**kw: Any) -> None:
    try:
        status = str(kw.get("status") or "ok").lower()
        if status == "ok":
            return
        msg = kw.get("error_message")
        perm = status == "blocked" or _is_perm_text(msg)
        obs_store.record(
            "tool_issue", name=kw.get("tool_name"), status=status, perm=perm,
            session_id=kw.get("session_id"), task_id=kw.get("task_id"), duration_ms=kw.get("duration_ms"),
            detail={"error_type": kw.get("error_type"), "error": _snippet(msg)},
        )
    except Exception:
        return


# --- auxiliary model calls -------------------------------------------------
def on_post_auxiliary_call(**kw: Any) -> None:
    try:
        usage = kw.get("usage") or {}
        err = kw.get("error")
        dur = kw.get("api_duration")
        obs_store.record(
            "aux_call", name=kw.get("aux_task") or "aux", status="error" if err else "ok",
            perm=bool(err) and _is_perm_text(err),
            session_id=kw.get("session_id"), task_id=kw.get("task_id"),
            model=kw.get("response_model") or kw.get("model"), provider=kw.get("provider"),
            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cache_read_tokens"), cache_write_tokens=usage.get("cache_write_tokens"),
            duration_ms=None if dur is None else float(dur) * 1000,
            detail={"error": _snippet(err)} if err else None,
        )
    except Exception:
        return


# --- main-model provider failures ------------------------------------------
def on_api_request_error(**kw: Any) -> None:
    try:
        code = kw.get("status_code")
        reason = kw.get("reason") or kw.get("error")
        perm = str(code) in {"401", "403"} or _is_perm_text(reason)
        obs_store.record(
            "api_error", name=str(code or kw.get("reason") or "error"), status="error", perm=perm,
            session_id=kw.get("session_id"), task_id=kw.get("task_id"),
            model=kw.get("model"), provider=kw.get("provider"),
            detail={"retryable": kw.get("retryable"), "error": _snippet(reason)},
        )
    except Exception:
        return


HOOKS = {
    "on_skill_lifecycle": on_skill_lifecycle,
    "subagent_start": on_subagent_start,
    "subagent_stop": on_subagent_stop,
    "pre_approval_request": on_pre_approval_request,
    "post_approval_response": on_post_approval_response,
    "post_tool_call": on_post_tool_call,
    "post_auxiliary_call": on_post_auxiliary_call,
    "api_request_error": on_api_request_error,
}
