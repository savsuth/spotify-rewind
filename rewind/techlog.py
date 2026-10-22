"""Technical-log cross-check. Log events are compared with the history, never counted as listens."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config


def reconcile_raw_core_stream(records: pd.DataFrame, log_dir: Path = config.TECH_LOG_DIR,
                              tolerance_s: float = 2.0) -> dict:
    path = Path(log_dir) / "RawCoreStream.json"
    if not path.exists():
        return {"available": False}
    with path.open(encoding="utf-8") as handle:
        log = pd.DataFrame(json.load(handle))
    log = log[["timestamp_utc", "message_ms_played", "message_content_uri"]].copy()
    log["t"] = pd.to_datetime(log["timestamp_utc"], utc=True, format="ISO8601")
    hist = records[~records["is_duplicate"]][["ts_utc", "track_uri", "ms_played"]].copy()
    lo, hi = log["t"].min(), log["t"].max()
    # pd.to_timedelta with an explicit unit; pd.Timedelta(seconds=...) trips a NumPy
    # "generic unit" deprecation under pandas 2.3.3 / NumPy 2.5.3.
    tol = pd.to_timedelta(tolerance_s, unit="s")
    window = hist[(hist["ts_utc"] >= lo - tol) & (hist["ts_utc"] <= hi + tol)]
    m = log.reset_index().merge(window, left_on="message_content_uri", right_on="track_uri", how="left")
    m["dt"] = (m["ts_utc"] - m["t"]).dt.total_seconds().abs()
    best = m.sort_values("dt").drop_duplicates("index")
    matched = best[best["dt"] <= tolerance_s]
    return {
        "available": True,
        "file": path.name,
        "log_events": int(len(log)),
        "log_window_utc": [str(lo), str(hi)],
        "history_records_in_window": int(len(window)),
        "matched_within_seconds": tolerance_s,
        "matched_events": int(len(matched)),
        "matched_with_identical_ms_played": int((matched["message_ms_played"] == matched["ms_played"]).sum()),
        "unmatched_events": int(len(log) - len(matched)),
        "interpretation": "Log stream events describe the same plays as the extended history; "
                          "they are used only as a cross-check and add no listens.",
    }
