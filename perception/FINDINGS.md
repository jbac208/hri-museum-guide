# Findings: perception's start impression in the processing loop (simulated)

For the paper. Everything here was run on 2026-11-17, branch `jay/perception`. Full tables: `perception/integration/results.md`; method and assumptions: `perception/README.md`.

## What was tested

Our perception front end (face detection and filtering, tracking, age band, companion clusters, engagement trigger) produced the `start_impression` that seeds Joey's processing loop. A scripted fake camera showed it the six simulated visitors of Joey's scenarios as they walked up to the robot. Our start impression replaced the scenario's own, and Joey's loop and measures ran unchanged:

- `s1_one_stop`: open loop, with ground-truth labels;
- `s1_closed`: one stop, closed loop;
- `s2_multi_stop`: three stops, closed loop.

Each condition ran 20 seeds, under policy `ours`. Values are mean [min–max].

## Conditions and results

| Condition | What differs from A | Result |
|---|---|---|
| **A** | Joey's own start impression: exact per-visitor distance to the exhibit, glance seeds 4/min (adult) and 6/min (child), his clusters | reference; reproduces his published comparison numbers exactly |
| **B** | ours, ages right; `distance_m` is a placeholder (2.2 m for everyone); our clusters | **s1: the excluded child (v2) is detected later.** Open loop: excluded latency 3.6 → 11.5 s, bid precision 1 → 0.72 [0.33–1.00]. Closed loop: first detection 53.6 → 62.0 s; exclusion episodes 2 → 1.90 [1–2]; time to resolve 2.38 → 2.50 [2.00–4.00] s; P13 0 in both. **s2: no difference.** |
| B + his `distance_m` (diagnostic) | B with the true distances copied back | identical to A in every measure and every per-visitor event |
| B + his `cluster_id` (diagnostic) | B with his clusters copied back | identical to B |
| **C-v1, C-v3, C-v4, C-v5, C-v6** | one adult read as a child (glance seed 4 → 6) | no visitor's events changed in any scenario, so all measures equal B |
| **C2** | the child read as an adult (6 → 4) | as C |
| **D** / **D-all** | the child / all six `unsure` (neutral seed 5.0) | as C |
| Level 2 | per-frame `track_conf`, `age_class`, `age_conf` and `cluster_id` also from ours | identical to B in 60/60 runs |

## What each result shows, and what it does not

- **The placeholder distance seed is the only thing that mattered.**
  - **Shows:** with these thresholds, a wrong prior on the child's distance hides the child's first bid to join (edging in) for about 8 s on average.
  - **Worst cases:** in 2 of 20 closed-loop seeds (3 and 10), the first exclusion episode was **never created**. The child stood with a blocked view from 2 s on, but no episode began until a later bid (77–78 s), which then combined both barriers. That one episode resolved in 4 s.
  - **Missed by the measures:** P13 counts only episodes still open at the end of a stop: `unresolved = [n for n in notes if n["note"].startswith("P13 misery")]` (`sdc/metrics.py:134`). Those notes come from `for tid, ep in self.episodes.items(): self._note(t, "P13 misery: …")` in `StopController.end_stop` (`sdc/decision.py:550-551`). So **P13 cannot see an episode that was never created, and time-to-resolve starts only at detection.** The measures stay good while the child waits longer.
  - **Does not show:** that a real distance sensor would fix it in practice. The diagnostic only shows that the *true scripted* distances do.
- **Age errors and `unsure` had no effect.**
  - **Shows:** in these scenarios the age-dependent glance seed never decides an event. The child's glance burst (12/min) clears the rate test under any seed, so the timing is set by the rule "2 short glances in 10 s".
  - **Does not show:** that age estimates are harmless in general. Joey's loop reads age only through the seed values, and his scenarios contain no adult glance bids for a misread to change.
- **Our clusters had no measurable effect,** because clusters only set which way the robot faces when it delivers an addition. But **our encounter split every companion pair** (in all 540 encounters). The impression is a snapshot at the first engagement event, and a lone visitor's group is known before a pair's.
- **The extra bids were all the child's own.** In B the child's single long bid split into two or three shorter ones (12 extra unlabelled detections over 20 open-loop seeds, all from v2). In the closed loop every exclusion fix, in A and in B, targeted the child; no other visitor was treated as excluded.

## Distance error sweep: how accurate must `distance_m` be?

Our impression with Joey's true distances copied in, plus an error on every visitor: a constant bias of ±0.1, ±0.3 or ±0.5 m, or random error (std 0.3 m). 20 seeds per scenario. With no error the result is identical to A. Full tables: `perception/integration/distance_sweep.md`.

| Error | v2 bid/excluded, open loop (A: 3.6 s after the bid starts) | False events | Misread rate, s1 closed / s2 (A: 0.39 / 0.24) |
|---|---|---|---|
| −0.1 / −0.3 / −0.5 m | 5.0 / 7.2 / 8.8 s | none | 0.36 / 0.35 / 0.35 · 0.24 |
| +0.1 m | fires at 1 s, 49 s **before** the child edges in (20/20 seeds) | v2's early bid | 0.39 · 0.23 |
| +0.3 / +0.5 m | as +0.1 | v2's early bid; an approach at 1–2 s from all 6 visitors (80 over 20 seeds); approach precision 1 → 0.25 / 0.20 | 0.66 / 0.71 · 0.54 / 0.65 |
| random, std 0.3 m | early in 10/20 seeds | 9 unlabelled approaches; approach precision 0.83 | 0.46 · 0.40 |

- **The cost of an error is asymmetric.**
  - **A distance too small** (the visitor seeded closer than they are) only delays the child, by about 1.4, 3.6 and 5.2 s at −0.1, −0.3 and −0.5 m. Detection then falls back to the glance rule. There were no false events; episodes stayed at 2 and P13 at 0. In s1_closed, v2's first bid moves from 53.6 s to 55.0, 57.2 and 58.8 s.
  - **A distance too large fires false events at once.** "Edging in" is a drop of at least `EDGE_MIN_DROP_M` = 0.06 m below the visitor's own baseline (`sdc/config.py:59`), so +0.1 m already makes the child "edge in" at 1 s, and the robot treats them as excluded at 2 s. From +0.3 m (`APPROACH_MIN_DROP_M` = 0.3, `config.py:40`) every visitor also "approaches" at 1–2 s, and the misread rate nearly doubles.
- **The measures miss the early false bid.** The overlap matcher (`eval_signals.match`, tolerance 5 s) counts the 1 s detection as a hit with a latency of −49 s, so bid precision stays 1. Exclusion episodes and P13 don't change either.
- **Consistent with condition B.** The 2.2 m placeholder is 0.8 m *below* v2's true 3.0 m, and B delayed v2 by about 8 s with no false events. That fits the under-estimate side of this sweep. Only bias and noise were run, not B's exact pattern.
- **Shows:** with Joey's thresholds, a distance source must not over-estimate. Over-estimates as small as 0.1 m produce false bids, while under-estimates cost seconds. A module that has to err should err short.
- **Does not show:** the error of any real sensor; errors that differ between visitors in a systematic way (for example a child's smaller face reading farther away, which is an over-estimate); or later stops, where s2 shows little effect because the seed's weight falls with each stop (30/15/0 s). Whether edging-in should rest on a seeded baseline at all is Joey's design question.

## Limits

- **The visitors are simulated by rules** (Joey's `sdc/sim.py`). These numbers show mechanisms, not effects on real visitors.
- **The camera scene is a construction.** The layout, the spacing (companions 0.3 face widths apart, clusters 2.5 apart), the child's face at 0.85× an adult's, and the age-estimator outputs are assumptions; they decide our clusters and ages. No real images were used.
- **Thresholds were not tuned,** in Joey's loop or in perception.
- **Real camera:** separately, one real-webcam run with one person showed the full front end firing as designed. It ran at ~1 frame per second, so frame-counted dwell took ~20 s. Several people, children and crossing paths were not tested on a real camera.
