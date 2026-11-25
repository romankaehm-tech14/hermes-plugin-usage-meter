"""Usage Meter — token and cost readout for the Hermes Desktop composer.

Mounted at /api/plugins/usage-meter/. Reads the canonical session store
($HERMES_HOME/state.db) and answers two questions:

  GET /today?tz=Europe/Berlin   -> spend since local midnight, all models
  GET /session/{session_id}     -> spend of one session, all models

Accuracy note: the store keeps per-session/per-model totals plus first_seen /
last_seen, not a per-call event log. A row that started before midnight is
therefore prorated by the share of that session's messages that fall inside the
window — cost tracks message volume closely enough for a live readout, and it
beats counting a week-old chat at full weight.
"""
from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import zoneinfo
from typing import Any

from fastapi import APIRouter, HTTPException

from hermes_constants import get_hermes_home

router = APIRouter()

DEFAULT_TZ = os.environ.get("HERMES_USAGE_METER_TZ", "Europe/Berlin")
_COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")


def _db_path() -> str:
    return str(get_hermes_home() / "state.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _empty_totals() -> dict[str, float]:
    t: dict[str, float] = {c: 0.0 for c in _COUNTERS}
    t["cost_usd"] = 0.0
    t["api_calls"] = 0.0
    return t


def _add(totals: dict[str, float], row: sqlite3.Row, weight: float) -> None:
    for c in _COUNTERS:
        totals[c] += (row[c] or 0) * weight
    totals["cost_usd"] += (row["estimated_cost_usd"] or 0) * weight
    totals["api_calls"] += (row["api_call_count"] or 0) * weight


def _finish(totals: dict[str, float]) -> dict[str, Any]:
    out = {k: (round(v) if k != "cost_usd" else round(v, 6)) for k, v in totals.items()}
    # "tokens" is the headline number: everything the model actually read or wrote,
    # cache reads excluded (they are ~20x the rest and would drown the readout).
    out["tokens"] = int(out["input_tokens"] + out["output_tokens"] + out["reasoning_tokens"])
    out["tokens_with_cache"] = int(out["tokens"] + out["cache_read_tokens"] + out["cache_write_tokens"])
    return out


def _window_start(tz_name: str) -> tuple[float, str]:
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = zoneinfo.ZoneInfo(DEFAULT_TZ)
    now = _dt.datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), now.date().isoformat()


def _weighted_rows(conn: sqlite3.Connection, start: float) -> list[tuple[sqlite3.Row, float]]:
    """Every usage row that reaches into the window, paired with its share of the window.

    A row that began before midnight is weighted by the share of its session's
    messages that fall inside the window; a fully-in-window row counts 1.0.
    """
    rows = conn.execute(
        """SELECT u.session_id, u.model, u.billing_provider, u.input_tokens, u.output_tokens,
                  u.cache_read_tokens, u.cache_write_tokens, u.reasoning_tokens,
                  u.estimated_cost_usd, u.api_call_count, u.first_seen, u.last_seen
             FROM session_model_usage u
            WHERE COALESCE(u.last_seen, 0) >= ?""",
        (start,),
    ).fetchall()

    msg_cache: dict[str, tuple[int, int]] = {}

    def share(session_id: str, first_seen: float | None) -> float:
        if (first_seen or 0) >= start:
            return 1.0
        if session_id not in msg_cache:
            r = conn.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS today
                     FROM messages WHERE session_id = ?""",
                (start, session_id),
            ).fetchone()
            msg_cache[session_id] = (int(r["total"] or 0), int(r["today"] or 0))
        total, today = msg_cache[session_id]
        return (today / total) if total else 0.0

    weighted: list[tuple[sqlite3.Row, float]] = []
    for row in rows:
        weight = share(row["session_id"], row["first_seen"])
        if weight > 0:
            weighted.append((row, weight))
    return weighted


def _aggregate(conn: sqlite3.Connection, start: float) -> dict[str, Any]:
    totals = _empty_totals()
    by_model: dict[tuple[str, str], dict[str, float]] = {}
    sessions: set[str] = set()
    partial = False
    for row, weight in _weighted_rows(conn, start):
        if weight < 1.0:
            partial = True
        _add(totals, row, weight)
        key = (row["model"] or "unknown", row["billing_provider"] or "")
        bucket = by_model.setdefault(key, _empty_totals())
        _add(bucket, row, weight)
        sessions.add(row["session_id"])

    models = [
        {"model": model, "provider": provider, **_finish(bucket)}
        for (model, provider), bucket in by_model.items()
    ]
    models.sort(key=lambda m: m["cost_usd"], reverse=True)
    return {
        "totals": _finish(totals),
        "by_model": models,
        "session_count": len(sessions),
        "prorated": partial,
    }


@router.get("/today")
def today(tz: str = DEFAULT_TZ) -> dict[str, Any]:
    start, day = _window_start(tz)
    conn = _connect()
    try:
        data = _aggregate(conn, start)
    finally:
        conn.close()
    return {"date": day, "tz": tz, "since": start, **data}


@router.get("/top")
def top(limit: int = 10, tz: str = DEFAULT_TZ) -> dict[str, Any]:
    """The most expensive sessions inside the window, with their titles."""
    start, day = _window_start(tz)
    conn = _connect()
    try:
        per: dict[str, dict[str, Any]] = {}
        for row, weight in _weighted_rows(conn, start):
            bucket = per.setdefault(row["session_id"], {"totals": _empty_totals(), "models": set()})
            _add(bucket["totals"], row, weight)
            bucket["models"].add(row["model"] or "unknown")
        out = []
        for sid, bucket in per.items():
            meta = conn.execute(
                "SELECT title, source FROM sessions WHERE id = ?", (sid,)
            ).fetchone()
            t = _finish(bucket["totals"])
            out.append({
                "session_id": sid,
                "title": (meta["title"] if meta and meta["title"] else "(ohne Titel)"),
                "source": (meta["source"] if meta else ""),
                "cost_usd": t["cost_usd"],
                "tokens": t["tokens"],
                "api_calls": int(t["api_calls"]),
                "models": sorted(bucket["models"]),
            })
    finally:
        conn.close()
    out.sort(key=lambda s: s["cost_usd"], reverse=True)
    return {"date": day, "tz": tz, "sessions": out[: max(1, min(int(limit), 50))]}


@router.get("/session/{session_id}")
def session_usage(session_id: str) -> dict[str, Any]:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT model, billing_provider, input_tokens, output_tokens, cache_read_tokens,
                      cache_write_tokens, reasoning_tokens, estimated_cost_usd, api_call_count
                 FROM session_model_usage WHERE session_id = ?""",
            (session_id,),
        ).fetchall()
        if not rows:
            exists = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="session not found")
    finally:
        conn.close()

    totals = _empty_totals()
    by_model: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        _add(totals, row, 1.0)
        key = (row["model"] or "unknown", row["billing_provider"] or "")
        _add(by_model.setdefault(key, _empty_totals()), row, 1.0)
    models = [
        {"model": m, "provider": p, **_finish(b)}
        for (m, p), b in sorted(by_model.items(), key=lambda kv: -(kv[1]["cost_usd"] or 0))
    ]
    return {"session_id": session_id, "totals": _finish(totals), "by_model": models}


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "db": _db_path(), "tz": DEFAULT_TZ}
