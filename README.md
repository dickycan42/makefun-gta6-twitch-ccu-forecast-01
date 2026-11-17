# GTA VI launch-day Twitch viewers — hour-by-hour forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/dickycan42/makefun-gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/dickycan42/makefun-gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Entry for the make.fun competition `gta6-twitch-ccu-forecast-01` ([bounty page](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)):
forecast the concurrent viewers in Twitch's Grand Theft Auto VI category
for each hour 2–24 of release day (2026-11-19 UTC), given only what is
known up to the end of hour 1.

## How it works

The program (`main.py`, Python 3.13, standard library only) reads a case
file and anchors everything on the hour-1 print:

1. **Shapes, not levels.** Each past launch in the case's `comparables`
   is reduced to its launch-day *shape*: the log ratio of every later
   hour's viewers to its own hour-1 viewers. Shapes transfer across
   launches of very different sizes; raw levels do not.
2. **Similarity weighting.** A comparable is weighted by how close its
   hour-1 crowd was to this case's hour 1, with a Gaussian kernel on the
   log scale (bandwidth 1.5). This is the step that matters most: a
   launch whose first hour drew a few hundred viewers routinely grows
   100x by evening, while a launch that opened at 800k barely doubles,
   so an unweighted average is dragged around by launches nothing like
   this one. Console-only launches are not given a special bonus — in
   validation it did not help, and the kernel already does the work.
   The pooled shapes also carry the day's unlock waves for free: most
   comparables unlocked at rolling midnight local time, so the average
   shape rises as New Zealand, central Europe, the UK, the US East Coast
   and the US West Coast come online through the UTC day.
3. **Honest quantiles.** For each hour, the forecast blends two views of
   the weighted log-ratio distribution: the weighted empirical quantiles
   (honest about the long upper tail) and a Gaussian from the weighted
   mean and standard deviation (stable where the tails are thin), 50/50.
   Exponentiated and multiplied by the hour-1 print, that gives the five
   quantiles at 0.05 / 0.25 / 0.5 / 0.75 / 0.95. The interval widens
   through the day because the launches genuinely disagree more later
   in the day.
4. **Fallback.** If no comparable can be used at all, the program falls
   back to a persistence forecast with a widening random-walk spread, so
   the output is always a valid forecast.

The target game's own pre-release category history (included among the
comparables) is not a launch and is skipped automatically: it has no
release-day hour 1.

Deterministic by construction: no network, no clock, no randomness, no
state between runs. The same input bytes always produce the same output
bytes.

## Local validation

Validated by leave-one-out over the 37 comparable launches: each launch
in turn was forecast from its hour-1 print alone using only the other 36,
and scored with the official log-scale pinball loss. The four practice
cases were also run end to end for shape, determinism and speed checks
(their answers are not in the kit, so they cannot be scored locally).

| Set | This forecaster | Persistence baseline |
| --- | --- | --- |
| All 37 launches (LOO) | **0.393** | 0.930 |
| Big launches, hour-1 ≥ 10,000 (LOO, n=28) | **0.260** | 0.351 |

The official baseline scores about 0.387 on the practice cases, so on
the practice-like big-launch set this forecaster beats it by roughly a
third. 90% interval coverage in leave-one-out: 0.879 over all launches,
0.907 over big launches (an honest 90% interval should cover about
0.90). Typical median miss: 0.39 in log units on big launches.

Determinism and speed (local runs on the four practice cases): two runs
produce byte-identical outputs; the whole run over all four cases takes
about 0.26 s (~0.06 s per case), far under the 8 s limit.

Sanity of the curves: the median typically dips slightly in hours 2–5,
then climbs through the unlock waves to roughly 1.5–2.5x the hour-1
print by the evening; the 5%–95% interval widens steadily with the hour,
as the launches disagree more later in the day.

## Running it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` in the input directory (or `/input` by default) and
writes one `<id>.out` per case to the output directory (or `/output`).
