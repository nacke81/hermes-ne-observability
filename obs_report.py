"""Rollups. Tokens/models/cost come from every profile's state.db (authoritative, includes history);
skills/subagents/approvals/permission issues come from the plugin's events.db (from install onward)."""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import obs_store


def _profile_dbs() -> List[tuple[str, Path]]:
    root = obs_store.hermes_root()
    out: List[tuple[str, Path]] = []
    if (root / "state.db").exists():
        out.append(("default", root / "state.db"))
    profiles = root / "profiles"
    if profiles.is_dir():
        for p in sorted(profiles.iterdir()):
            if p.is_dir() and not p.name.startswith(".") and (p / "state.db").exists():
                out.append((p.name, p / "state.db"))
    return out


def _ro(path: Path) -> Optional[sqlite3.Connection]:
    try:
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2.0)
    except Exception:
        return None


def _boards() -> List[tuple[str, str, Path]]:
    """(slug, display name, kanban.db) for every live board. 'default' is the root kanban.db."""
    root = obs_store.hermes_root()
    out: List[tuple[str, str, Path]] = []
    if (root / "kanban.db").exists():
        out.append(("default", "Default", root / "kanban.db"))
    bdir = root / "kanban" / "boards"
    if bdir.is_dir():
        for d in sorted(bdir.iterdir()):
            if not d.is_dir() or d.name.startswith(("_", ".")) or not (d / "kanban.db").exists():
                continue
            name = d.name
            try:
                meta = json.loads((d / "board.json").read_text(encoding="utf-8"))
                if meta.get("archived"):
                    continue
                name = meta.get("name") or d.name
            except Exception:
                pass
            out.append((d.name, name, d / "kanban.db"))
    return out


def _board_runs() -> Dict[str, List[tuple]]:
    """profile -> sorted [(worker_start, end, board)] from every board's task_runs."""
    runs: Dict[str, List[tuple]] = defaultdict(list)
    for slug, _name, path in _boards():
        conn = _ro(path)
        if conn is None:
            continue
        try:
            for prof, st, ws, en in conn.execute(
                    "SELECT profile, started_at, worker_started_at, ended_at FROM task_runs"
                    " WHERE profile IS NOT NULL AND started_at IS NOT NULL"):
                runs[prof].append((float(ws or st), float(en) if en else None, slug))
        except Exception:
            pass
        finally:
            conn.close()
    for v in runs.values():
        v.sort()
    return runs


def _match_board(runs: List[tuple], started: float) -> Optional[str]:
    """Board of the run that was live when this worker session started (latest start wins)."""
    best = None
    for st, en, slug in runs:
        if st - 120 > started:
            break
        if en is None or started <= en + 5:
            best = slug
    return best


def _cron_jobs(profile_home: Path) -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads((profile_home / "cron" / "jobs.json").read_text(encoding="utf-8"))
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        if isinstance(jobs, dict):
            jobs = list(jobs.values())
        return {str(j.get("id")): j for j in jobs if isinstance(j, dict) and j.get("id")}
    except Exception:
        return {}


def _cron_id(sid: str, source: str) -> Optional[str]:
    if sid.startswith("cron_"):
        parts = sid.split("_")
        return parts[1] if len(parts) > 1 else None
    return "?" if source == "cron" else None


def _usage(cut: float, board: str = "") -> Dict[str, Any]:
    per_profile: Dict[str, Dict[str, float]] = {}
    by_model: Dict[tuple, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    aux_tasks: Dict[tuple, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    crons: Dict[tuple, Dict[str, Any]] = {}
    board_sids: set = set()
    runs = _board_runs()
    sql = (
        "SELECT session_id, model, coalesce(billing_provider,''), coalesce(task,''), sum(api_call_count),"
        " sum(input_tokens), sum(output_tokens), sum(cache_read_tokens), sum(cache_write_tokens),"
        " sum(coalesce(actual_cost_usd, estimated_cost_usd, 0)), max(last_seen)"
        " FROM session_model_usage WHERE last_seen >= ? GROUP BY 1,2,3,4"
    )
    for profile, path in _profile_dbs():
        conn = _ro(path)
        if conn is None:
            continue
        try:
            rows = conn.execute(sql, (cut,)).fetchall()
            meta = {sid: (src or "", float(st or 0), par) for sid, src, st, par in conn.execute(
                "SELECT id, source, started_at, parent_session_id FROM sessions")}
        except Exception:
            rows, meta = [], {}
        finally:
            conn.close()

        root_memo: Dict[str, tuple] = {}

        def origin(sid: str) -> tuple:
            """(board or None, cron job id or None) for a session, following subagent parents."""
            if sid in root_memo:
                return root_memo[sid]
            seen, cur, res = set(), sid, (None, None)
            while cur and cur not in seen:
                seen.add(cur)
                src, st, par = meta.get(cur, ("", 0.0, None))
                cid = _cron_id(cur, src)
                if cid:
                    res = (None, cid)
                    break
                if src == "kanban":
                    res = (_match_board(runs.get(profile, []), st), None)
                    break
                cur = par
            root_memo[sid] = res
            return res

        sessions = 0
        for sid, (src, st, _par) in meta.items():
            if st < cut:
                continue
            b = origin(sid)[0]
            if board and b != board:
                continue
            sessions += 1
            if b:
                board_sids.add(sid)
        if board:
            board_sids.update(s for s in meta if origin(s)[0] == board)

        jobs = _cron_jobs(path.parent)
        agg = defaultdict(float)
        agg["sessions"] = sessions
        for sid, model, provider, task, calls, inp, out, cr, cw, cost, seen in rows:
            b, cid = origin(sid or "")
            if board and b != board:
                continue
            kind = "aux" if task else "main"
            calls, inp, out, cr, cw, cost = (x or 0 for x in (calls, inp, out, cr, cw, cost))
            if cid:
                j = jobs.get(cid, {})
                c = crons.setdefault((profile, cid), {
                    "profile": profile, "job_id": cid, "job": j.get("name") or ("(unknown job)" if cid == "?" else cid),
                    "enabled": j.get("enabled") if j else None, "schedule": j.get("schedule_display") or "",
                    "sessions": set(), "main_calls": 0, "aux_calls": 0, "input_tokens": 0, "output_tokens": 0,
                    "cache_read_tokens": 0, "cost_usd": 0.0, "models": set(), "last_ts": 0.0})
                c["sessions"].add(sid)
                c[f"{kind}_calls"] += calls
                c["input_tokens"] += inp; c["output_tokens"] += out; c["cache_read_tokens"] += cr
                c["cost_usd"] += cost
                c["models"].add(model or "?")
                c["last_ts"] = max(c["last_ts"], float(seen or 0))
            agg[f"{kind}_calls"] += calls
            agg[f"{kind}_input"] += inp
            agg[f"{kind}_output"] += out
            agg[f"{kind}_cache_read"] += cr
            agg[f"{kind}_cost"] += cost
            m = by_model[(model or "?", provider, kind)]
            m["calls"] += calls; m["input"] += inp; m["output"] += out; m["cache_read"] += cr; m["cost"] += cost
            if task:
                a = aux_tasks[(profile, task)]
                a["calls"] += calls; a["tokens"] += inp + out; a["cost"] += cost
                a.setdefault("models", set()).add(model or "?")  # type: ignore[union-attr]
        if any(agg.get(k) for k in ("main_calls", "aux_calls", "sessions")):
            per_profile[profile] = dict(agg)

    profiles = []
    for name, a in per_profile.items():
        calls = a.get("main_calls", 0) + a.get("aux_calls", 0)
        toks = sum(a.get(k, 0) for k in ("main_input", "main_output", "aux_input", "aux_output"))
        aux_toks = a.get("aux_input", 0) + a.get("aux_output", 0)
        profiles.append({
            "profile": name, "sessions": int(a.get("sessions", 0)),
            "main_calls": int(a.get("main_calls", 0)), "aux_calls": int(a.get("aux_calls", 0)),
            "aux_call_pct": round(100 * a.get("aux_calls", 0) / calls, 1) if calls else 0.0,
            "main_tokens": int(a.get("main_input", 0) + a.get("main_output", 0)),
            "aux_tokens": int(aux_toks),
            "aux_token_pct": round(100 * aux_toks / toks, 1) if toks else 0.0,
            "cache_read_tokens": int(a.get("main_cache_read", 0) + a.get("aux_cache_read", 0)),
            "cost_usd": round(a.get("main_cost", 0) + a.get("aux_cost", 0), 2),
        })
    profiles.sort(key=lambda r: -(r["main_tokens"] + r["aux_tokens"]))

    models = [{"model": k[0], "provider": k[1], "role": k[2], "calls": int(v["calls"]),
               "input_tokens": int(v["input"]), "output_tokens": int(v["output"]),
               "cache_read_tokens": int(v["cache_read"]), "cost_usd": round(v["cost"], 2)}
              for k, v in by_model.items()]
    models.sort(key=lambda r: -(r["input_tokens"] + r["output_tokens"]))

    aux = [{"profile": k[0], "aux_task": k[1], "calls": int(v["calls"]), "tokens": int(v["tokens"]),
            "cost_usd": round(v["cost"], 2), "models": sorted(v.get("models", ()))}  # type: ignore[arg-type]
           for k, v in aux_tasks.items()]
    aux.sort(key=lambda r: -r["tokens"])

    tot = defaultdict(float)
    for r in profiles:
        for k in ("sessions", "main_calls", "aux_calls", "main_tokens", "aux_tokens", "cache_read_tokens", "cost_usd"):
            tot[k] += r[k]
    calls = tot["main_calls"] + tot["aux_calls"]
    toks = tot["main_tokens"] + tot["aux_tokens"]
    instance = {k: (round(v, 2) if k == "cost_usd" else int(v)) for k, v in tot.items()}
    instance["aux_call_pct"] = round(100 * tot["aux_calls"] / calls, 1) if calls else 0.0
    instance["aux_token_pct"] = round(100 * tot["aux_tokens"] / toks, 1) if toks else 0.0
    instance["profiles_active"] = len(profiles)

    cron_rows = []
    for c in crons.values():
        c["runs"] = len(c.pop("sessions"))
        c["models"] = sorted(c["models"])
        c["tokens"] = c["input_tokens"] + c["output_tokens"]
        c["cost_usd"] = round(c["cost_usd"], 2)
        cron_rows.append(c)
    cron_rows.sort(key=lambda r: -r["tokens"])
    return {"instance": instance, "profiles": profiles, "models": models, "aux_tasks": aux[:40],
            "crons": cron_rows, "_board_sids": board_sids}


def _events(cut: float, board_sids: Optional[set] = None) -> Dict[str, Any]:
    """board_sids=None: no board filter. A set: only events whose session belongs to that board."""
    conn = obs_store.read_conn()
    empty = {"since": None, "skills": [], "skills_by_profile": [], "subagents": [], "permissions": [],
             "permission_issues": [], "event_counts": {}}
    if conn is None:
        return empty
    try:
        since = conn.execute("SELECT min(ts) FROM events").fetchone()[0]
        src = "events"
        if board_sids is not None:
            conn.execute("CREATE TEMP TABLE bs (sid TEXT PRIMARY KEY)")
            conn.executemany("INSERT OR IGNORE INTO bs VALUES (?)", ((s,) for s in board_sids))
            conn.execute("CREATE TEMP VIEW ev AS SELECT * FROM main.events WHERE session_id IN (SELECT sid FROM bs)")
            src = "ev"

        def q(sql: str, *a: Any) -> List[Dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql.replace("FROM events", "FROM " + src), (cut, *a)).fetchall()]
        skills = q("SELECT name AS skill, count(*) AS triggers, count(DISTINCT profile) AS profiles,"
                   " max(ts) AS last_ts FROM events WHERE ts>=? AND kind='skill' AND status='loaded'"
                   " GROUP BY name ORDER BY triggers DESC LIMIT 40")
        skills_by_profile = q("SELECT profile, name AS skill, count(*) AS triggers FROM events"
                              " WHERE ts>=? AND kind='skill' AND status='loaded'"
                              " GROUP BY profile, name ORDER BY profile, triggers DESC")
        subagents = q("SELECT profile, sum(kind='subagent_start') AS spawned,"
                      " sum(kind='subagent_stop') AS finished,"
                      " sum(kind='subagent_stop' AND coalesce(status,'') NOT IN ('completed','ok','success','done'))"
                      " AS not_ok, round(avg(CASE WHEN kind='subagent_stop' THEN duration_ms END)/1000.0,1)"
                      " AS avg_seconds FROM events WHERE ts>=? AND kind IN ('subagent_start','subagent_stop')"
                      " GROUP BY profile ORDER BY spawned DESC")
        permissions = q("SELECT profile, count(*) AS issues,"
                        " sum(kind='approval_response') AS approvals_denied_or_timed_out,"
                        " sum(kind='tool_issue' AND status='blocked') AS tools_blocked,"
                        " sum(kind='tool_issue' AND status<>'blocked') AS tool_permission_errors,"
                        " sum(kind IN ('aux_call','api_error')) AS provider_auth_errors"
                        " FROM events WHERE ts>=? AND perm=1 GROUP BY profile ORDER BY issues DESC")
        approvals = q("SELECT profile, count(*) AS requested FROM events WHERE ts>=? AND kind='approval_request'"
                      " GROUP BY profile")
        req = {r["profile"]: r["requested"] for r in approvals}
        for r in permissions:
            r["approvals_requested"] = req.pop(r["profile"], 0)
        for prof, n in req.items():
            permissions.append({"profile": prof, "issues": 0, "approvals_denied_or_timed_out": 0,
                                "tools_blocked": 0, "tool_permission_errors": 0, "provider_auth_errors": 0,
                                "approvals_requested": n})
        recent = q("SELECT ts, profile, kind, name, status, detail FROM events WHERE ts>=? AND perm=1"
                   " ORDER BY ts DESC LIMIT 25")
        counts = {r["kind"]: r["n"] for r in q("SELECT kind, count(*) AS n FROM events WHERE ts>=? GROUP BY kind")}
        return {"since": since, "skills": skills, "skills_by_profile": skills_by_profile, "subagents": subagents,
                "permissions": permissions, "permission_issues": recent, "event_counts": counts}
    except Exception:
        return empty
    finally:
        conn.close()


def build(days: int = 30, board: str = "") -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    cut = time.time() - days * 86400
    board = (board or "").strip()
    out: Dict[str, Any] = {"days": days, "board": board, "generated_at": time.time(),
                           "boards": [{"slug": s, "name": n} for s, n, _ in _boards()]}
    usage = _usage(cut, board)
    sids = usage.pop("_board_sids")
    out.update(usage)
    out.update(_events(cut, sids if board else None))
    return out


def _n(x: float) -> str:
    x = float(x or 0)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= div:
            return f"{x / div:.1f}{suf}"
    return str(int(x))


def markdown(rep: Dict[str, Any], top: int = 12) -> str:
    i = rep["instance"]
    since = rep.get("since")
    lines = [
        f"## Hermes observability, last {rep['days']} days" + (f", board {rep['board']}" if rep.get("board") else ""),
        "",
        f"Instance: {i.get('profiles_active', 0)} active profiles, {i.get('sessions', 0)} sessions, "
        f"{_n(i.get('main_tokens'))} main tokens + {_n(i.get('aux_tokens'))} aux tokens, "
        f"${i.get('cost_usd', 0):.2f}. Aux share: {i.get('aux_call_pct', 0)}% of calls, "
        f"{i.get('aux_token_pct', 0)}% of tokens.",
        "",
        "### By profile",
        "| Profile | Sessions | Main tok | Aux tok | Aux % calls | Cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rep["profiles"][:top]:
        lines.append(f"| {r['profile']} | {r['sessions']} | {_n(r['main_tokens'])} | {_n(r['aux_tokens'])} | "
                     f"{r['aux_call_pct']}% | ${r['cost_usd']:.2f} |")
    lines += ["", "### By model", "| Model | Role | Calls | Tokens | Cost |", "|---|---|---:|---:|---:|"]
    for r in rep["models"][:top]:
        lines.append(f"| {r['model']} | {r['role']} | {r['calls']} | "
                     f"{_n(r['input_tokens'] + r['output_tokens'])} | ${r['cost_usd']:.2f} |")
    lines += ["", "### Top aux tasks", "| Profile | Aux task | Calls | Tokens |", "|---|---|---:|---:|"]
    for r in rep["aux_tasks"][:top]:
        lines.append(f"| {r['profile']} | {r['aux_task']} | {r['calls']} | {_n(r['tokens'])} |")
    lines += ["", "### Crons", "| Profile | Job | Runs | Tokens | Cost |", "|---|---|---:|---:|---:|"]
    for r in rep.get("crons", [])[:top]:
        lines.append(f"| {r['profile']} | {r['job']} | {r['runs']} | {_n(r['tokens'])} | ${r['cost_usd']:.2f} |")
    note = "" if since else " (no hook events captured yet)"
    lines += ["", f"### Skills triggered{note}", "| Skill | Triggers | Profiles |", "|---|---:|---:|"]
    for r in rep["skills"][:top]:
        lines.append(f"| {r['skill']} | {r['triggers']} | {r['profiles']} |")
    lines += ["", "### Subagents", "| Profile | Spawned | Not ok | Avg s |", "|---|---:|---:|---:|"]
    for r in rep["subagents"][:top]:
        lines.append(f"| {r['profile']} | {r['spawned']} | {r['not_ok'] or 0} | {r['avg_seconds'] or 0} |")
    lines += ["", "### Permission issues", "| Profile | Issues | Approvals asked | Denied/timeout | Blocked | Perm errors | Auth |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rep["permissions"][:top]:
        lines.append(f"| {r['profile']} | {r['issues']} | {r['approvals_requested']} | "
                     f"{r['approvals_denied_or_timed_out'] or 0} | {r['tools_blocked'] or 0} | "
                     f"{r['tool_permission_errors'] or 0} | {r['provider_auth_errors'] or 0} |")
    if since:
        lines += ["", f"_Hook events captured since {time.strftime('%Y-%m-%d %H:%M', time.localtime(since))}._"]
    return "\n".join(lines)
