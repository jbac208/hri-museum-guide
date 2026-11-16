# Interface notes: perception → `start_impression` (schema v0.1)

For Joey. What `perception/encounter.py` emits, where it differs from `sdc/schema.py`, what is a placeholder, and the open questions. Nothing in `sdc/` was changed.

## What Joey's loop actually reads

From `sdc/signals.py` and `sdc/profile.py`:

- **Read:** `cluster_id`, `pending_layers`, `baseline_seed.distance_m` (baseline for *approach*) and `baseline_seed.robot_glances_per_min` (baseline for the *bid* glance cue).
- **How much the two seeds weigh:** at stop 1 each counts like `SEED_WEIGHT_S` (30 s) of observation, half that at stop 2, and nothing from stop 3. A placeholder here changes behaviour.
- **Validated, never read:** `age_class`, `age_conf`, `speech_frac`, `responded_to_steer_invite`, `group.size` and `group.spread_m`.

## Mismatches and what the code does

What the validator accepts:

- **Extra fields:** accepted. `validate_start_impression` checks only the keys it requires, and `sdc/adapter.py` ignores the rest (a test checks both).
- **Null:** rejected in every required field.
- **Types and ranges:** `group.size` must be an int and `responded_to_steer_invite` a real bool. No range is checked anywhere.

| Field | Schema | Perception produces | Emitted |
|---|---|---|---|
| `track_id` | str | `visitor_N` from the tracker | as is. Joey's mock frames use `v1…`, so the two don't line up (see the README). |
| `age_class` | `child` \| `adult` | `child` \| `adult` \| `unsure` (abstains on purpose) | `argmax(p_child, p_adult)`; a tie gives `adult`. Question 1. |
| `age_conf` | number | `max(p_child, p_adult)`, 8-frame mean of FairFace mass; not calibrated | that value. The teen (10–19) mass counts for neither, so a teenager gets a low `age_conf`. |
| *(extra)* `age_band`, `p_child`, `p_adult` | not in schema | smoother output | added per visitor, so `unsure` isn't lost |
| `cluster_id` | str, never null | companion cluster `group_N`, or unknown (settling, merge, above a cap of 6, lone visitor not yet settled) | known → `group_N`; unknown → `solo_<track_id>`, so no companionship is claimed |
| `group.size` | int | cluster size per group (`None` when unknown) | **meaning differs.** Joey's `size` is the whole tour group (mock: 6 visitors, 4 clusters), so it's set to the number of visitors in the impression. Question 2. |
| `group.spread_m` | metres | nothing (image plane only) | PLACEHOLDER |
| `baseline_seed.*` | metres / per min / fraction | nothing | PLACEHOLDER |
| `responded_to_steer_invite` | bool | nothing | PLACEHOLDER `false` |
| `pending_layers` | list | n/a | always `[]`. Interests are never guessed from appearance. |
| `t` | number | seconds since perception started, at the engagement event | that value. Question 6. |
| *(extra)* `placeholder_fields` | not in schema | n/a | names every unmeasured field (top level) |

**Who is included:** every visitor in view at the engagement event who passed `filter_faces` and the stable-frame gate (5 consecutive frames, configurable). That's not only the cluster that triggered the event. **A bystander standing near the group is included too.** Joey's D9 says only tour members count, and nothing at the encounter can tell a member from a bystander. Question 9.

## Placeholders (one block: `PLACEHOLDER` in `perception/encounter.py`)

The values are copied from Joey's mock (`sdc/mock.py`, `World.start_lines`), so his loop behaves as in his own simulations.

| Field | Value | What it would take to measure |
|---|---|---|
| `group.spread_m` | 1.96 (the mock's s1 value) | Metric visitor positions: a depth sensor (Pepper's 3D camera) or a calibrated ground-plane mapping for a fixed camera. Then the mock's formula: max distance from the centroid. |
| `baseline_seed.distance_m` | 2.2 | Distance to the **exhibit** needs metric visitor positions plus the exhibit's position in the robot's map. The face-box ratio we have gives distance to the **camera**, only after per-site calibration (never done with measured distances), and children's smaller faces read as farther away. |
| `baseline_seed.robot_glances_per_min` | adult 4.0, child 6.0, **unsure 5.0** (midpoint) | A head-pose or gaze model (none here), counting glance onsets per minute during the encounter. The age-dependent values are the mock's choice, not a measurement. Question 8. |
| `baseline_seed.speech_frac` | 0.05 | A microphone, voice-activity detection and speaker attribution. This code has no audio input. |
| `responded_to_steer_invite` | `false` | The robot first has to issue a "you can steer" invitation (no such behaviour exists), then detect a response by speech or movement. The owner is open (question 7). |

## Frames (out of scope)

No per-frame geometry is produced (`x`, `y`, yaws, `attention`, `los_*`, `in_formation`, `posture`, `pointing_at`); it stays on Joey's mock. The frame fields the code could fill today, per visitor:

- `track_id`: the same tracker
- `track_conf`: 0–1 heuristic, not a probability
- `age_class`, `age_conf`: forced binary as above
- `cluster_id`: with the `solo_` fallback

## Questions for Joey

1. `unsure`: should it become a third `age_class`, stay a forced binary with its real low `age_conf` (current), or should those visitors be left out?
2. `group.size`: is it the whole tour group or one companion cluster? How large can a tour be? Clustering reports unknown above 6.
3. Could the seed fields be nullable ("no prior", seed weight 0)? Right now the placeholders count as 30 s of real observation at stop 1.
4. `distance_m` is distance to the exhibit, but at the encounter the robot only sees distance to itself. Do you want robot distance, exhibit distance, or nothing?
5. How should encounter ids carry over to frame ids once frames come from real perception? It would be one tracker for both.
6. `t`: should it be 0, or seconds since perception started (current)?
7. Who owns `responded_to_steer_invite`? Nothing issues a steering invitation yet.
8. Your loop never reads `age_class` or `age_conf`. The age prior only acts through the seed values, and only the mock sets those. Who maps age band to baseline seed, and with what values?
9. Who counts as a tour member at the encounter, and how should bystanders be kept out (D9)?
