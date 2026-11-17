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

## Limits

- **The visitors are simulated by rules** (Joey's `sdc/sim.py`). These numbers show mechanisms, not effects on real visitors.
- **The camera scene is a construction.** The layout, the spacing (companions 0.3 face widths apart, clusters 2.5 apart), the child's face at 0.85× an adult's, and the age-estimator outputs are assumptions; they decide our clusters and ages. No real images were used.
- **Thresholds were not tuned,** in Joey's loop or in perception.
- **Real camera:** separately, one real-webcam run with one person showed the full front end firing as designed. It ran at ~1 frame per second, so frame-counted dwell took ~20 s. Several people, children and crossing paths were not tested on a real camera.
