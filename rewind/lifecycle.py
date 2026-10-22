"""Per-artist lifecycle: first observed, sustained engagement, peak, comebacks.

"First observed" means first within this export (from its first month), not
first in the listener's life. Artists already present in the first two export
months are marked left-censored: the export cannot say when they entered.
"""

from __future__ import annotations

import numpy as np

from . import config
from .eras import MonthlySpace


def engaged_matrix(space: MonthlySpace) -> np.ndarray:
    shares = space.shares
    ok_month = space.total_minutes >= config.LOW_ACTIVITY_MINUTES
    return (shares >= config.ENGAGED_SHARE) & (space.minutes >= config.ENGAGED_MIN_MINUTES) & ok_month[:, None]


def artist_lifecycles(space: MonthlySpace, year_tops: dict[str, list[str]]) -> list[dict]:
    """year_tops: year -> list of artist IDs in that year's top N by minutes."""
    months = space.months
    n = len(months)
    engaged = engaged_matrix(space)
    present = space.minutes > 0
    absent = space.minutes < config.ABSENT_MAX_MINUTES
    out = []
    for j, aid in enumerate(space.artist_ids):
        col_min = space.minutes[:, j]
        total = float(col_min.sum())
        if total < 60:  # under an hour across five years: not a lifecycle story
            continue
        first = int(np.argmax(present[:, j]))
        eng_idx = np.flatnonzero(engaged[:, j])
        rec = {
            "id": aid,
            "name": space.artist_names[aid],
            "total_minutes": round(total, 1),
            "first_observed": months[first],
            "left_censored": first <= 1,
            "engaged_months": int(len(eng_idx)),
            "first_engaged": months[eng_idx[0]] if len(eng_idx) else None,
            "last_engaged": months[eng_idx[-1]] if len(eng_idx) else None,
            "years_in_top": sorted(y for y, ids in year_tops.items() if aid in ids),
        }
        # Sustained engagement: >= SUSTAINED_MIN engaged months in the 12 starting at first engagement.
        if len(eng_idx):
            f = eng_idx[0]
            window_end = f + config.SUSTAINED_WINDOW
            if window_end > n:
                rec["sustained"] = None  # insufficient follow-up
                rec["sustained_status"] = "insufficient follow-up"
                rec["engaged_in_first_window"] = int(engaged[f:, j].sum())
            else:
                k = int(engaged[f:window_end, j].sum())
                rec["engaged_in_first_window"] = k
                rec["sustained"] = k >= config.SUSTAINED_MIN
                rec["sustained_status"] = "sustained" if rec["sustained"] else "not sustained"
        else:
            rec["sustained"] = False
            rec["sustained_status"] = "never engaged"
        # Peak: the 3 consecutive calendar months with the most minutes (earliest on ties).
        if n >= 3:
            roll = np.convolve(col_min, np.ones(3), mode="valid")
            p = int(np.argmax(roll))
            rec["peak_start"], rec["peak_end"] = months[p], months[p + 2]
            win_total = float(space.total_minutes[p:p + 3].sum())
            rec["peak_minutes"] = round(float(roll[p]), 1)
            rec["peak_share"] = round(float(roll[p] / win_total), 4) if win_total else 0.0
        # Monthly rank 1 count and best monthly rank.
        ranks = []
        for i in range(n):
            if col_min[i] <= 0:
                continue
            row = space.minutes[i]
            ranks.append(int((row > col_min[i]).sum()) + 1)
        rec["best_monthly_rank"] = min(ranks) if ranks else None
        # Comebacks: engaged before, then >= COMEBACK_GAP_MONTHS absent months, then engaged again.
        comebacks = []
        i = 0
        seen_engaged = False
        while i < n:
            if engaged[i, j]:
                seen_engaged = True
                i += 1
                continue
            if seen_engaged and absent[i, j]:
                g = i
                while g < n and absent[g, j]:
                    g += 1
                gap = g - i
                if gap >= config.COMEBACK_GAP_MONTHS and g < n:
                    # Return month: first engaged month at or after the gap ends, if any,
                    # before the artist goes absent again.
                    r = g
                    while r < n and not engaged[r, j] and not absent[r, j]:
                        r += 1
                    if r < n and engaged[r, j]:
                        after = float(col_min[r:r + 3].sum())
                        before_idx = np.flatnonzero(engaged[:i, j])
                        comebacks.append({
                            "last_engaged_before": months[before_idx[-1]],
                            "gap_start": months[i],
                            "gap_end": months[g - 1],
                            "gap_months": int(gap),
                            "return_month": months[r],
                            "minutes_3m_after_return": round(after, 1),
                            "minutes_during_gap": round(float(col_min[i:g].sum()), 1),
                            "share_return_month": round(float(space.shares[r, j]), 4),
                        })
                i = g
                continue
            i += 1
        rec["comebacks"] = comebacks
        out.append(rec)
    out.sort(key=lambda r: (-r["total_minutes"], r["name"].casefold()))
    return out
