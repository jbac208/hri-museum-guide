# perception/ (Jay's initial encounter)

Runs perception from a camera until a visitor group is close enough to engage, then emits one `start_impression` (schema v0.1, validated with `sdc.schema.validate_start_impression`).

The code is ported from Jay's repo `HRI-2027-SDC-Museum-Guide-robot`, branch `museum-visual-profile`; see `docs/AUDIT_museum_code.md` there.

The package is separate from `sdc/`:
- `sdc/` is unchanged, stays standard-library only, and never imports `perception/`.
- `python3 run_tests.py` runs exactly as before.

**The real start impression can't drive the simulated tour yet.** Its track ids (`visitor_N`) don't match the ids in Joey's mock frames (`v1…`), and frames still come from the mock. So it is a schema-valid hand-over and nothing more. No id remapping exists.

## Install

```
pip install -r perception/requirements-perception.txt
```

Two model files are needed. Neither is committed.

- **FairFace (age band):** `~/.fairface/fairface.onnx`, about 85 MB, from HF `garavv/fairface-onnx`. Its SHA-256 must be `e26179a4125c0c51fa73676f4b38b2013e9abe7d20ccc4ca19192dc9e2825971`; a mismatch refuses to load. It is not downloaded automatically.
- **VGGFace2 weights (face embeddings):** facenet-pytorch downloads these into `~/.cache/torch/checkpoints/20180402-114759-vggface2.pt` the first time the webcam path runs.

## Run

```
python3 -m perception.run_encounter --source fake                  # scripted, deterministic; numpy only
python3 -m perception.run_encounter --source webcam --camera 0     # MTCNN + FaceNet + FairFace on CPU
    [--max-s 120] [--stable-frames 5] [--out si.json]
```

- **Output:** one JSON line on stdout, or in `--out`. Pipe it through `python3 -m json.tool` to read it.
- **Exit code:** 1 if no engagement event happened.
- **Webcam progress:** one status line per second on stderr, covering faces, band, streak, track confidence, box ratio, gate, cluster and engagement state.
- **The fake scene:** an adult, a teenager (band `unsure`) and a child with a smaller face walk up together. There is also a poster face (dropped by `filter_faces`) and a face seen in one frame only (never passes the gate).

## Tests

```
python3 -m pytest perception/tests     # 85 tests; files needing numpy skip cleanly without it
python3 run_tests.py                   # Joey's 99 tests, unchanged; never sees perception/tests
```

Both commands were also run in clean venvs:
- **Only pytest installed:** 32 passed, and the 4 numpy-dependent files skipped.
- **Nothing installed:** `run_tests.py` still passes 99.

## What is real, what is a placeholder, what is not verified

| | |
|---|---|
| **Real (computed from frames)** | `track_id` (IoU plus embedding-cosine tracker) · `track_conf` (heuristic) · age band and `p_child`/`p_adult` (FairFace age logits only; a weak prior) · companion clusters (image-plane proximity and co-movement) · the engagement moment `t` · `group.size` (count of stable visitors in view) |
| **Forced to fit the schema** | `age_class` = argmax, even when the band is `unsure` · `cluster_id` = `solo_<id>` when the cluster is unknown |
| **Placeholder** (named in `placeholder_fields`) | `group.spread_m`, `baseline_seed.distance_m`, `baseline_seed.robot_glances_per_min`, `baseline_seed.speech_frac`, `responded_to_steer_invite`. Values come from Joey's mock; see `INTERFACE_NOTES.md` for what each would take to measure. |
| **Never produced** | `pending_layers` (always `[]`) · per-frame geometry (stays on Joey's mock) |

**Not verified:**
- **The whole pipeline on a real camera:** stable-frame gate, clusters and engagement together. See the webcam run below.
- **`detect_and_embed` with a real face.** Its only test is a blank frame, which returns `[]`.
- **FairFace accuracy on real children, teenagers and adults.** The race/gender discard and the 10–19 bin are tested only with a fake ONNX session.
- **Re-identification thresholds** `reid_min_cos` 0.6 / `reid_gap` 0.1. The different-person cosine range was never measured.
- **Cluster and engagement thresholds on real people.** They are placeholders and untuned.
- **`filter_faces` defaults outside Jay's lab.** The 0.5 area and 0.18 height floors were measured there only.
- **Files written on the webcam path.** The no-files test covers the fake path only. The webcam path may write the torch weight cache on first use.
- **CPU frame rate.** Engagement counts frames (`dwell_frames` 20), so a slow camera loop takes longer in seconds to trigger.
- **Joey's loop running on a real impression.** It can't yet, because the ids don't match.

**Known issue, not fixed:** a passer-by walking slowly through the near field triggers engagement every time (Jay's simulator: `passer_by_near` 1.00). The fix is a speed or stillness gate plus a new simulator run.

## Not moved (stays in Jay's repo)

- **The knowledge-graph profile and its wrappers:** `profile.py`, `profile_api.py`, `profile_extraction.py`, `profiling_policy.py`. Joey's repo has no knowledge graph; its profile store is `sdc/profile.py`.
- **The opening logic:** `initiation.py` and `opening_for_event`.
- **The demo app and simulators:** `live.py`, `live_ui.html`, `simulate.py`, `simulate_tracking.py`.
- **Logging and threading:** `worker.py`, `decision_log.py`.
- **ChatBox internals:** `ai_server_llm.py`, `graph_relationship/`, `kg_extraction.py`, `session_store.py`.
- **Also left behind:** `ephemeral.py` (the no-files test covers the privacy point), `create_estimator`, `calibrate_engagement.py`.

## Work log (`jay/perception`)

Every commit ran `python3 run_tests.py` (99 passed, with system Python and in a venv with nothing installed) and `python3 -m pytest perception/tests` (with deps, and in a venv with only pytest).

- **A, scaffold + tracker** (`3088a34`). This added `perception/`, its requirements and `tracker.py`. Config is a dict merged over `DEFAULTS`; the values are the same as Jay's old YAML. 11 tracker tests.
- **B1, age band** (`4c72d90`). This added `age.py`. The model path and SHA live in the code, and the race/gender-discard and 10–19-bin tests moved with it. `create_estimator` (dead code) and `AgeBandWorker` (unused) stayed behind.
- **B2, face source** (`ac84c04`). This added `faces.py`: `load_detect_and_embed()` returns `detect_and_embed(frame) -> [Detection]`. It uses MTCNN (prob ≥ 0.90) and InceptionResnetV1/VGGFace2, with `MTCNN.extract` on the kept boxes so detection runs once instead of twice. `filter_faces` moved from `live.py`.
- **B3, companion clusters** (`2294044`). This added `group.py`; the logic is unchanged. 14 of 17 tests moved; the three wiring tests need `initiation`/`profile_api`.
- **B4, engagement** (`7c54fe8`).
  - Bug fixed: the settle timeout carried the generic `UNKNOWN` (`no_track`) instead of the tracker's real reason. The new test failed before the fix and passes after.
  - The passer-by false trigger is documented, not fixed.
  - `opening_for_event` stayed behind.
- **D, E, G: encounter, adapter, run script** (`992c4c4`).
  - **Gate and wipe:** the stable-frame gate is `STABLE_FRAMES` = 5 (configurable). `end()` wipes tracks, embeddings, smoothers, clusters and the gate, and `run()` calls it in a `finally`.
  - **Mismatch choices:** the start impression applies the choices in `INTERFACE_NOTES.md`.
  - **Tests:**
    - A full fake run in an empty folder with an empty `$HOME` writes only `--out`.
    - Joey's adapter parses the result.
    - Import boundaries hold.
    - Mutation checks: a stray file, a skipped gate and a skipped wipe each make the matching tests fail.
- **Docs** (this commit). This adds this README and `INTERFACE_NOTES.md`.
- **H, webcam run:** pending.
