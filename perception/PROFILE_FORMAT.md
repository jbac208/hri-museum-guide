# Joey's profile store, and what perception can put in it

Read from the code on `main` at `dfc86ed`; `sdc/` is unchanged. Every claim names the file and function it comes from. "Line" numbers are from that commit.

## 1. The record kept per visitor

The store is `ProfileStore` (`sdc/profile.py`). It keeps one `VisitorProfile` per track id in `ProfileStore.visitors`.

`VisitorProfile` (`sdc/profile.py:53-57`):

| field | type | meaning |
|---|---|---|
| `track_id` | str | the visitor's id |
| `cluster_id` | str | companion cluster, from the start impression; `"?"` if the visitor was never in it (`ProfileStore._visitor`, l.77-80) |
| `credit` | float, starts at 0.0 | steering credit k_i (D8) |
| `layers` | dict `(kind, target)` → `Layer` | profile layers, at most one per kind and target |

`Layer` (`sdc/profile.py:31-49`):

| field | type | meaning |
|---|---|---|
| `id` | str | `L1`, `L2`, … (`ProfileStore._new`, l.189-192) |
| `track_id` | str | the owner |
| `kind` | str | made by signal events: `feature_interest`, `depth` or `exhibit_interest` (`config.LAYER_FROM_EVENT`, `sdc/config.py:79-84`). From the start impression: **any string** (see §2) |
| `target` | str | a feature id (`feature_interest`) or an exhibit id (`depth`, `exhibit_interest`) |
| `status` | str | `pending`, `confirmed` or `rescinded`. No other value is ever set (`_new`, `_set`), but none is rejected either. |
| `confidence` | float, 0..1 | see below |
| `created_t`, `updated_t` | float | stream time |
| `evidence` | list of `(t, source, reason)` | every event that touched it |
| `strength` (property) | float | its contribution to an addition's score s_i(a): confirmed 1, pending `PENDING_WEIGHT` (0.5) × confidence, rescinded 0 (l.42-49) |

### How confidence and status change

Each step names where in the code it happens:

1. **Create, pending.** A `linger`, `approach` or `drift` event creates a pending layer at `LAYER_EVENT_CONF`: 0.5, 0.4 and 0.5 (`config.py:85`; `ProfileStore.on_event`, l.102-121). A start-impression layer is created at `SEED_LAYER_CONF` = 0.3 (`load_start_impression`, l.70-75). `fatigue`, `bid`, `barrier` and `excluded` create no layers (`LAYER_FROM_EVENT` has no entry for them).
2. **Strengthen.** More of the same evidence on a pending layer gives conf ← 1 − (1 − conf)(1 − event_conf) (`on_event`, l.126-131).
3. **Confirm, confidence 1.0** (`_set`, l.194-198). This happens in two ways:
   - an explicit point or question creates or confirms the layer at once (`_confirm_by_ask`, l.134-145). A question with no pointed feature becomes `exhibit_interest` on the current stop (l.109-110).
   - uptake seen after an addition (`StopController._close_uptake` → `profile.confirm`, `sdc/decision.py:510`).
4. **Rescind.** No uptake within `UPTAKE_WINDOW_S` after an addition rescinds the layer (`decision.py:515` → `ProfileStore.rescind`). Its confidence is kept, but its strength becomes 0.
5. **While rescinded.** More of the same evidence is ignored (D6, `on_event`, l.123-125). A point or question re-confirms it, because `POINT_ASK_REOPENS_RESCINDED = True` (l.141; `config.py:90`).
6. **Between stops.** Rescinded layers are deleted; untested pending ones stay (`end_stop`, l.165-173).
7. **Tour end.** Everything is cleared, and only a count is returned (`end_tour`, l.175-180).

### Steering credit

- **How credit grows:** `add_credit` (l.156-163) adds `CREDIT_PER_ACTED_SIGNAL` = 1.0 (`config.py:118`) when the robot answers that visitor's question (`decision.py:462`), and to every visitor an addition was scored for when it is delivered, taken up or not (`decision.py:497`).
- **How credit sets weight:** `weight()` is w = 1/(1 + λk), with λ = `LAMBDA_DOMINANCE` 0.5 (l.94-96; `config.py:89`), or 0 in the engagement baseline (`ProfileStore.__init__`, l.62).
- **Where weight is used:** in `score_addition` (`decision.py:70-77`) and the next-stop planner (`decision.py:613`).

### The other per-visitor state: signal-layer baselines

Per-visitor baselines are **not** in `ProfileStore`. They live in `SignalLayer.v[tid]` (`sdc/signals.py`, `_Visitor`, `_new_visitor` l.217-224). Two of them come from the start impression (§2).

## 2. How a start_impression visitor becomes store state

**The path.** `adapter.parse` turns the JSON line into `StartImpression` and `VisitorSeed` (`sdc/adapter.py:91-100`). Then:
- `Loop.step` (`sdc/loop.py:41-43`) and `Tour.step` (`sdc/tour.py:101-103`) call `ProfileStore.load_start_impression`;
- `SignalLayer.step` (`sdc/signals.py:183-185`) calls `_new_visitor(seed)` for every visitor.

| field | read? | effect |
|---|---|---|
| `track_id` | yes | key of the `VisitorProfile` and the signal-layer state. **Only these ids are ever processed.** `SignalLayer._on_frame` skips frame visitors it has no state for (`signals.py:277-279`), and `_on_utterance` drops their speech (l.317-319). |
| `cluster_id` | yes | `VisitorProfile.cluster_id`. Used once: an addition is delivered facing the centroid of the top visitor's cluster (`decision.py:486-492`, via `ProfileStore.cluster`). |
| `pending_layers` | yes | one pending layer each at confidence 0.3. **Any `kind` and `target` strings are accepted** (`schema.validate_start_impression` only checks they are strings, and `load_start_impression` doesn't check them). A layer counts only if some addition's `serves` lists the same kind and target (`content.Addition.serves_layer`, `decision.score_addition`); otherwise it sits there unused. |
| `baseline_seed.robot_glances_per_min` | yes | prior of the robot-glance-rate baseline (the bid cue) (`_new_visitor`, l.222) |
| `baseline_seed.distance_m` | yes | prior of the distance-to-exhibit baseline (approach and edging in), set on the first tick for the visitor's in- or out-of-formation state (`signals.py:404-406`) |
| `t` | only as `created_t` of seed layers | |
| `age_class`, `age_conf` | **no** | validated, then never read. A grep of `sdc/` finds them only where they are checked or set (`schema.py`, `adapter.py`, `mock.py`, `sim.py` and `scenarios.py`), never where they are used. |
| `baseline_seed.speech_frac` | **no** | validated, never read |
| `responded_to_steer_invite` | **no** | validated, never read |
| `group.size`, `group.spread_m` | **no** | read into `StartImpression`, never used |
| extra fields (`age_band`, `p_child`, `p_adult`, `placeholder_fields`) | **no** | not rejected by the validator, dropped by `adapter.parse` |

**What the two seeds do.**
- **The weight.** Each is a `Baseline` prior with weight `seed_weight(stop_index)` = `SEED_WEIGHT_S` × (1 − stop_index / `SEED_FADE_STOPS`), which is 30, 15, then 0 from the third stop on (`signals.py:46-48`; `config.py:21-22`). `SignalLayer.set_stop` re-applies it at each stop (l.144-155).
- **The units are seconds.** Baselines get one sample per 1 s tick, weighted by tick length (`signals.py:504-511`; `SIGNAL_TICK_S` = 1.0).
- **What that means:** at the first stop a seed counts as much as 30 s of the visitor's own behaviour. A wrong seed therefore shifts when *approach*, *edging in* and the *glance bid* fire at stops 1 and 2.
- **Baselines not from the seed:** dwell (`DWELL_PRIOR_S`), other-exhibit gaze, posture and facing away (`STATE_PRIOR_FRAC`) (l.221-225).

Frame fields `cluster_id`, `age_class` and `age_conf` are also never read downstream: `signals.py` and `decision.py` have no reference to them. Frame `track_conf` is read: frames below `MIN_TRACK_CONF` 0.6 are skipped (`signals.py:278`).

## 3. Real output: our fake encounter loaded into Joey's store

The script below runs `perception.run_encounter`'s `FakeCamera` through `Encounter`, then hands the result to Joey's `adapter.parse`, `ProfileStore.load_start_impression` and `SignalLayer.step`. No frame follows.

```python
cam = FakeCamera()
si = Encounter(cam.estimator, cam.detect).run(cam.frames())
rec = adapter.parse(si)
store = ProfileStore(); store.load_start_impression(rec)
sig = SignalLayer(gallery, "figurehead", 0); sig.step(rec)
```

Output (2026-11-17, `jay/perception` at `e53529e`):

```
adapter.parse -> StartImpression t = 6.4 group_size = 3 group_spread_m = 1.96
  VisitorSeed(track_id='visitor_1', age_class='adult', age_conf=0.928, cluster_id='group_3', distance_m=2.2, robot_glances_per_min=4.0, speech_frac=0.05, pending_layers=[], responded_to_steer_invite=False)
  VisitorSeed(track_id='visitor_2', age_class='adult', age_conf=0.353, cluster_id='group_3', distance_m=2.2, robot_glances_per_min=5.0, speech_frac=0.05, pending_layers=[], responded_to_steer_invite=False)
  VisitorSeed(track_id='visitor_3', age_class='child', age_conf=0.873, cluster_id='group_3', distance_m=2.2, robot_glances_per_min=6.0, speech_frac=0.05, pending_layers=[], responded_to_steer_invite=False)

ProfileStore.visitors before any frame:
  visitor_1: cluster_id='group_3' credit=0.0 weight=1.000 layers={}
  visitor_2: cluster_id='group_3' credit=0.0 weight=1.000 layers={}
  visitor_3: cluster_id='group_3' credit=0.0 weight=1.000 layers={}
ProfileStore.log: []

SignalLayer baselines before any frame (stop index 0, seed weight = SEED_WEIGHT_S=30.0 s):
  visitor_1: glance_rate prior=4.0 weight=30.0 value=4.0 | distance prior not set yet (dist_seeded=False; seeded from seed.distance_m=2.2 on the first tick) | dwell prior=4.0 (5 runs, not from the seed)
  visitor_2: glance_rate prior=5.0 weight=30.0 value=5.0 | distance prior not set yet (dist_seeded=False; seeded from seed.distance_m=2.2 on the first tick) | dwell prior=4.0 (5 runs, not from the seed)
  visitor_3: glance_rate prior=6.0 weight=30.0 value=6.0 | distance prior not set yet (dist_seeded=False; seeded from seed.distance_m=2.2 on the first tick) | dwell prior=4.0 (5 runs, not from the seed)
seed weight by stop index: {0: 30.0, 1: 15.0, 2: 0.0, 3: 0.0}

illustration, NOT sent by perception: two pending_layers entries on visitor_1 ->
  L1 feature_interest figurehead.carving pending conf=0.3 strength=0.15
  L2 made_up_kind anything pending conf=0.3 strength=0.15
```

**What this shows.**
- **Store record before any frame:** after loading, the profile record holds only the id and `cluster_id`, with zero credit, weight 1 and no layers.
- **Where everything else goes:** the start impression's other effects all land in the two signal-layer seeds.
- **Age reaches the loop only through the seed numbers.** `age_class` itself is gone after parsing.
- **The last lines are an illustration only:** perception never sends `pending_layers`, but the store would take any kind, even a made-up one (`L2`).

## 4. What perception may put in an initial profile, and what must come from behaviour

| Item | From perception? | Why (code and rules) |
|---|---|---|
| Identity (`track_id`) | **yes** | Session-scoped: `ProfileStore.end_tour` and `Encounter.end` wipe it. It decides who the loop tracks at all (`signals.py:277-279`). |
| Companion cluster (`cluster_id`) | **yes** | Read and used: facing the cluster for additions (`decision.py:486-492`). An unknown cluster is sent as `solo_<id>`, so no companionship is claimed. |
| Age band, **only as a baseline seed** | **yes**, within D4 | CLAUDE.md: "Never add appearance-based features beyond child/adult (D4)"; HANDOFF §4: "child/adult only seeds baselines". In the code, age acts only through `robot_glances_per_min` (and `distance_m`, if someone mapped age to it). Who maps age to seed values is open (INTERFACE_NOTES Q8). |
| Steer response (`responded_to_steer_invite`) | **yes**, if measured | It is a response to an invitation, i.e. behaviour, not appearance. It is never read by the code today, and nothing issues the invitation (Q7). |
| Interests and depth (`pending_layers`) | **no**, from appearance | D4, and design principle 3 ("next stop counts confirmed guesses only", HANDOFF Q12): layers start from behaviour events (`LAYER_FROM_EVENT`). Perception sees only faces, so it sends `[]`. Behaviour seen *during the encounter* (e.g. pointing at an exhibit) would be a legitimate source, but nothing in perception observes it. |
| Steering credit, weights | **no** | Only the robot's own actions change credit (`decision.py:462`, `497`). |
| Confirm / rescind | **no** | Only uptake or a question does (`decision.py:510-515`, `_confirm_by_ask`). |
| Gender, race, personality, relationships | **never** | D4. `perception/age.py` discards FairFace's race and gender logits; `group.py` gives no relationship labels. |

## 5. What a "brief initial profile from perception" can mean without changing the schema

Within schema v0.1 and the current code it can only be:

1. **Who** is in the group (the ids). This also fixes who the loop will ever track.
2. **Who came with whom** (`cluster_id`). This affects which way the robot faces when it delivers an addition.
3. **Two baseline priors per visitor** (`distance_m`, `robot_glances_per_min`). These affect when approach, edging-in and glance bids fire at the first two stops; they count for nothing from the third stop on.
4. **Optionally, pending layers from behaviour seen at the encounter.** These start at confidence 0.3 and must still be confirmed by uptake. Perception sends none today.

Anything else in the start impression is carried and validated but has no effect: `age_class`, `age_conf`, `speech_frac`, `responded_to_steer_invite`, `group.*`, and the extra fields `age_band`, `p_child`, `p_adult` and `placeholder_fields`. These would only matter after a change to Joey's code, not to the schema:
- `unsure` as a class;
- confidence in a cluster;
- reading which fields are placeholders;
- using `speech_frac`.

Those are questions for Joey (INTERFACE_NOTES.md), not something perception can add on its own.
