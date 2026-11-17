"""Forecast GTA VI launch-day Twitch concurrent viewers, hour by hour.

Entry for make.fun competition gta6-twitch-ccu-forecast-01.

The program reads one case file per run (schema makefun/twitch-ccu-case/v1):
everything known up to the end of release day's first hour, including the
hour-1 print and the hourly curves of dozens of past big game launches
(the comparables). For each of hours 2..24 it writes five quantiles
(0.05, 0.25, 0.5, 0.75, 0.95) of that hour's concurrent-viewer count.

Method (see README.md for the full story):

  * Anchor on hour 1.  Every comparable launch is reduced to its own
    launch-day shape: the log ratio of each later hour's viewers to its
    own hour-1 viewers.  Shapes, not levels, are what transfer across
    launches of very different sizes.
  * Weight the comparables by how similar their hour-1 crowd was to this
    case's hour 1, with a Gaussian kernel on the log scale (bandwidth 1.5):
    a launch whose first hour drew a similar crowd counts far more than
    one that drew a hundred times fewer or more.  This matters because
    tiny first hours (a few hundred viewers) routinely explode by 100x
    later in the day while huge first hours barely double, so an
    unweighted average would be dragged around by launches nothing like
    this one.
  * For each hour, combine two views of the weighted log-ratio
    distribution: the weighted empirical quantiles (honest about the
    skew -- the upper tail is long) and a Gaussian with the weighted
    mean and standard deviation (stable where the tails are thin).
    The forecast quantiles are the 50/50 blend of the two, exponentiated
    back and multiplied by this case's hour-1 print.  The blend keeps the
    median honest and the interval wide enough to cover the real
    between-launch spread, which grows through the day as the regional
    unlock waves (New Zealand, central Europe, the UK, US East, US West)
    roll in at different hours for different launches.
  * If no comparable can be used at all (missing data), fall back to a
    persistence forecast with a widening random-walk spread, so the
    output is always a valid forecast.

Guarantees: standard library only, no network, no clock, no randomness,
no state between runs.  The same input bytes always produce the same
output bytes.  Runs in well under a second per case.

Usage:
    MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
"""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at the scored levels.
Z_SCORES = [-1.6448536269514722, -0.6744897501960817, 0.0,
            0.6744897501960817, 1.6448536269514722]
# Gaussian kernel bandwidth on log hour-1 viewers: how fast a comparable's
# weight falls off as its first-hour crowd differs from this case's.
KERNEL_WIDTH = 1.5
# Fallback spread (log units per sqrt hour) when no comparable is usable.
FALLBACK_SIGMA = 0.15
MAX_VIEWERS = 1_000_000_000


def parse_time(text):
    """Parse an ISO 8601 UTC timestamp into a datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def round_half_up_2dp(value):
    """Round to 2 decimals, halves away from zero; ints stay ints in JSON."""
    scaled = value * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    rounded = whole / 100.0
    return int(rounded) if float(rounded).is_integer() else rounded


def day_curve(comparable):
    """Map release-day hour (1..24) -> viewers for one comparable launch.

    Returns an empty dict when the comparable has no usable release day
    (e.g. the target game's own pre-release category history, which is
    not a launch at all).
    """
    try:
        start = parse_time(comparable["day_start"])
    except (KeyError, TypeError, ValueError):
        return {}
    curve = {}
    for point in comparable.get("hourly") or []:
        try:
            viewers = point["viewers"]
            when = parse_time(point["from"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(viewers, (int, float)) or not math.isfinite(viewers):
            continue
        if viewers <= 0:
            continue
        hour = int((when - start).total_seconds() // 3600) + 1
        if 1 <= hour <= 24 and hour not in curve:
            curve[hour] = float(viewers)
    return curve


def similarity_weight(log_first, log_target):
    """Gaussian kernel weight: 1 when first hours match, fading with distance."""
    gap = (log_first - log_target) / KERNEL_WIDTH
    return math.exp(-gap * gap)


def weighted_quantile(pairs, level):
    """Smallest value whose cumulative weight reaches `level` of the total."""
    total = sum(w for _, w in pairs)
    running = 0.0
    for value, weight in sorted(pairs):
        running += weight
        if running >= level * total:
            return value
    return sorted(pairs)[-1][0]


def weighted_mean_and_std(pairs):
    """Weighted mean and (population) standard deviation of the values."""
    total = sum(w for _, w in pairs)
    mean = sum(v * w for v, w in pairs) / total
    variance = sum(w * (v - mean) ** 2 for v, w in pairs) / total
    return mean, math.sqrt(variance)


def hour_log_quantiles(hour, first_print, comparables):
    """Forecast log-quantiles of hour `hour`'s ratio to hour 1, or None.

    `comparables` is a list of (log hour-1 viewers, day curve) pairs.
    Only launches with a valid hour-1 and a valid value for this hour
    take part, so a sparse launch still contributes where it can.
    """
    log_target = math.log(first_print)
    pairs = []
    for log_first, curve in comparables:
        if 1 not in curve or hour not in curve:
            continue
        weight = similarity_weight(log_first, log_target)
        pairs.append((math.log(curve[hour] / curve[1]), weight))
    if not pairs:
        return None
    mean, spread = weighted_mean_and_std(pairs)
    empirical = [weighted_quantile(pairs, level) for level in LEVELS]
    normal = [mean + z * spread for z in Z_SCORES]
    blended = [0.5 * e + 0.5 * n for e, n in zip(empirical, normal)]
    return blended


def clamp_quantiles(values, first_print):
    """Turn log-ratio quantiles into viewer counts, valid by construction."""
    out = []
    previous = 0.0
    for log_ratio in values:
        count = first_print * math.exp(log_ratio)
        if not math.isfinite(count) or count <= 0:
            count = previous if previous > 0 else first_print
        count = min(count, float(MAX_VIEWERS))
        count = max(count, previous)
        out.append(round_half_up_2dp(count))
        previous = count
    return out


def fallback_quantiles(first_print, hour):
    """Persistence with a widening spread, used only with no comparables."""
    spread = FALLBACK_SIGMA * math.sqrt(hour - 1)
    return [round_half_up_2dp(min(max(
        first_print * math.exp(z * spread), 1.0), float(MAX_VIEWERS)))
        for z in Z_SCORES]


def forecast_case(case, name):
    """Forecast one case: {"hours": [{"hour": h, "q": [...]}, ...]}."""
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name}: unexpected levels {case.get('levels')}")
    known = case.get("known") or []
    first = next((row for row in known if row.get("hour") == 1), None)
    if first is None:
        raise ValueError(f"{name}: no hour-1 print")
    first_print = max(1.0, float(first["viewers"]))

    comparables = []
    for comp in case.get("comparables") or []:
        curve = day_curve(comp)
        if 1 in curve:
            comparables.append((math.log(curve[1]), curve))

    rows = []
    for row in case.get("forecast") or []:
        hour = int(row["hour"])
        log_q = hour_log_quantiles(hour, first_print, comparables)
        if log_q is None:
            quantiles = fallback_quantiles(first_print, hour)
        else:
            quantiles = clamp_quantiles(log_q, first_print)
        rows.append({"hour": hour, "q": quantiles})
    rows.sort(key=lambda r: r["hour"])
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
