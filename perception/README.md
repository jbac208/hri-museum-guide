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
    [--max-s 120] [--stable-frames 5] [--out si.json] [--show]
```

- **Output:** one JSON line on stdout, or in `--out`. Pipe it through `python3 -m json.tool` to read it.
- **Exit code:** 1 if no engagement event happened; 2 if `--out` could not be written. In that case the impression goes to stdout instead, and no other file is written.
- **Webcam progress:** one status line per second on stderr. It shows `fired=yes/no`, the raw MTCNN faces before `filter_faces` (`raw=N[ratios]`), and for each tracked face its band, streak, track confidence, box ratio, gate, cluster and engagement state. The run ends by printing the highest box ratio per visitor and the highest raw ratio.
- **Live view:** `--show` opens a window with the boxes and states; `q` stops the take. Nothing is written.
- **The fake scene:** an adult, a teenager (band `unsure`) and a child with a smaller face walk up together. There is also a poster face (dropped by `filter_faces`) and a face seen in one frame only (never passes the gate).

## Tests

```
python3 -m pytest perception/tests     # 93 tests; files needing numpy skip cleanly without it
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

**Verified once on a real camera** (see "Webcam run" below): the full path, with stable-frame gate, clusters, engagement and the start impression, for **one person** standing still (take 1b). Also: `detect_and_embed` on a real face, re-identification after ~10 s out of view, no event for one walk-across, and only `si.json` written.

**Not verified:**
- **More than one person on a real camera:** two or more people, a child, crossing paths, a group arriving together. Take 3 was not run.
- **FairFace accuracy on real children, teenagers and adults.** The race/gender discard and the 10–19 bin are tested only with a fake ONNX session.
- **Re-identification thresholds** `reid_min_cos` 0.6 / `reid_gap` 0.1. The different-person cosine range was never measured.
- **Cluster and engagement thresholds on real people.** They are placeholders and untuned.
- **`filter_faces` defaults outside Jay's lab.** The 0.5 area and 0.18 height floors were measured there only.
- **Files written on the webcam path, beyond these takes.** The automated no-files test covers the fake path only. In the webcam takes nothing but `si.json` was written, but the weights were already cached; on first use the webcam path downloads the torch weight cache.
- **What limits the frame rate.** It was ~1 fps with one tracked face and ~19–23 fps with none. The likely cause is FairFace competing with torch for CPU threads, but that is a guess, not a measurement. Because engagement counts frames (`dwell_frames` 20), the trigger time in seconds depends on CPU speed.
- **Joey's loop running on a real impression.** It can't yet, because the ids don't match.

**Known issues, not fixed:**
- **Near-field passer-by false trigger.** A passer-by walking slowly through the near field triggers engagement every time (Jay's simulator: `passer_by_near` 1.00). On the webcam at ~1 fps one crossing did not fire, but only because 20 frames lasted ~20 s. The fix is a speed or stillness gate plus a new simulator run.
- **A walking person can split into two ids** (take 2b; inferred).

## Webcam run (H), 2026-11-17

**Setup**
- **Camera:** `/dev/video0`, a Verbatim 1080p Full HD Webcam. Over 30 frames it read 640×480 at mean brightness 54.1–113.3 in the run's OpenCV (pip 4.13, V4L2), and 1920×1080 at 139.8–192.2 in the system OpenCV (GStreamer). `/dev/video1` is not a capture device.
- **Thresholds:** none were changed; all defaults as committed.
- **Interpreter:** Python 3.10 on CPU, with ROS's `PYTHONPATH` set as in Jay's normal shell.
- **Harness:** each take ran through a script (not in the repo). It runs from a fresh empty output folder, lists the folder afterwards, and lists every file written in `$HOME` or the repo during the take, excluding browser, editor and Claude folders.
- **What the logs contain:** the progress lines are exactly as printed on stderr, minus OpenCV `[ WARN` lines and Qt font warnings.
- **Not run:** take 3 (two people). Jay ended the session after take 2b.

| Run | Result | Output folder afterwards |
|---|---|---|
| setup check (15 s) | no event (time ran out mid-dwell) | empty |
| `--show` smoke test (10 s) | no event | empty |
| take 1a, alone | **fired** at 52.9 s; JSON lost (harness error, see below) | its directory had been deleted |
| take 1b, alone | **fired** at 26.8 s, solo `group_known`, adult 0.80 | `si.json` only |
| take 2, walk across | aborted by Jay (`q`) before crossing | empty |
| raw-detection smoke test (6 s) | no event | empty |
| take 2b, walk across | **no event**; peak ratio 0.256 | empty |

**What this run showed**
- **The full live path works on a real camera:** stable-frame gate, clusters, engagement and the start impression, for one person (take 1b). Take 1a also showed re-identification after ~10 s out of view.
- **Frame rate depends on what is in view.** With one tracked face it was about 1 fps; with only filtered-out faces, about 19–23 fps. Background faces are still embedded, so the likely bottleneck is the per-tracked-face FairFace call, perhaps from onnxruntime and torch competing for CPU threads. Inferred, not measured.
- **The trigger is slow.** `dwell_frames` 20 lasts about 20 s at that frame rate, which makes engagement take 22–27 s from first appearance.
- **The passer-by false trigger was not seen in take 2b, but only because the pipeline is slow.** The crossing passed the gate and started counting. At the 10 fps the simulator assumed, the same 20 frames last 2 s. The known near-field false trigger stands. The thresholds count frames, not seconds.
- **A walking person may split into two ids** (take 2b), as above.
- **Two background faces in this room** sit at ratios 0.07–0.11, and `filter_faces` dropped them every frame.
- **Not covered:** two people (no take 3), a child, crossing paths, and a group arriving together.

### Setup check, 15 s (not a take; Jay seated at the keyboard)

No event: 16 frames in 15 s, so 15 s ran out mid-dwell. Ratio 0.28–0.34. Band `unsure` for 4 frames, then `adult` 0.73. Output folder empty. Other files written in that window: Slack and YouTube Music only.

<details><summary>stderr, exactly as printed (code at 86fee25)</summary>

```
[   0.0s] fired=no 1 face(s) visitor_1:unsure(0.77) streak=1 conf=0.6 ratio=0.30 unstable group=unknown/no_track engage=idle
[   1.7s] fired=no 1 face(s) visitor_1:unsure(0.75) streak=3 conf=1.0 ratio=0.31 unstable group=unknown/no_track engage=idle
[   2.7s] fired=no 1 face(s) visitor_1:unsure(0.74) streak=4 conf=1.0 ratio=0.33 unstable group=unknown/no_track engage=idle
[   3.7s] fired=no 1 face(s) visitor_1:adult(0.73) streak=5 conf=1.0 ratio=0.33 stable group=unknown/settling engage=counting
[   4.8s] fired=no 1 face(s) visitor_1:adult(0.74) streak=6 conf=1.0 ratio=0.29 stable group=unknown/settling engage=counting
[   5.8s] fired=no 1 face(s) visitor_1:adult(0.74) streak=7 conf=1.0 ratio=0.34 stable group=group_1 engage=counting
[   6.8s] fired=no 1 face(s) visitor_1:adult(0.74) streak=8 conf=1.0 ratio=0.33 stable group=group_1 engage=counting
[   7.9s] fired=no 1 face(s) visitor_1:adult(0.74) streak=9 conf=1.0 ratio=0.31 stable group=group_1 engage=counting
[   9.9s] fired=no 1 face(s) visitor_1:adult(0.74) streak=11 conf=1.0 ratio=0.29 stable group=group_1 engage=counting
[  10.9s] fired=no 1 face(s) visitor_1:adult(0.74) streak=12 conf=1.0 ratio=0.28 stable group=group_1 engage=counting
[  11.9s] fired=no 1 face(s) visitor_1:adult(0.75) streak=13 conf=1.0 ratio=0.28 stable group=group_1 engage=counting
[  13.0s] fired=no 1 face(s) visitor_1:adult(0.74) streak=14 conf=1.0 ratio=0.32 stable group=group_1 engage=counting
[  14.0s] fired=no 1 face(s) visitor_1:adult(0.74) streak=15 conf=1.0 ratio=0.32 stable group=group_1 engage=counting
16 frames; max face-box ratio (enter_ratio 0.20): visitor_1=0.335
no engagement event; no start_impression
```

</details>

### `--show` smoke test, 10 s

The window opened and closed with the run. 130 frames in 10 s, mostly no face. A face appeared now and then (ratio 0.19–0.25 printed, peak 0.410 unprinted), but its streak kept breaking, so it never passed the gate. Output folder empty. The Qt `QFontDatabase` warnings were removed from this log; they are harmless, and the overlay uses OpenCV's own fonts.

<details><summary>stderr, exactly as printed (code at a59cf54)</summary>

```
[   0.0s] fired=no 0 face(s) 
[   1.0s] fired=no 0 face(s) 
[   2.1s] fired=no 0 face(s) 
[   3.2s] fired=no 0 face(s) 
[   4.2s] fired=no 0 face(s) 
[   5.3s] fired=no 1 face(s) visitor_1:unsure(0.69) streak=1 conf=0.6 ratio=0.19 unstable group=unknown/no_track engage=idle
[   6.3s] fired=no 0 face(s) 
[   7.4s] fired=no 1 face(s) visitor_1:unsure(0.61) streak=3 conf=1.0 ratio=0.21 unstable group=unknown/no_track engage=idle
[   8.4s] fired=no 0 face(s) 
[   9.5s] fired=no 1 face(s) visitor_1:adult(0.68) streak=2 conf=1.0 ratio=0.25 unstable group=unknown/no_track engage=idle
130 frames; max face-box ratio (enter_ratio 0.20): visitor_1=0.410
no engagement event; no start_impression
```

</details>

### Take 1a, alone, 120 s. Started from Jay's terminal; **the JSON was lost, through a harness error**

This take started from Jay's terminal at the same moment as a second `take.sh take1` from the agent. The agent's copy could not open the busy camera (`camera 0 did not open`), but it had already emptied the take folder, which deleted this run's working directory.

- **0–22 s, seated:** ratio 0.21–0.31. Band `unsure` 0.47–0.54, then `adult`. Cluster `group_1` (a known solo) from 5.5 s. Engagement counted 19 of the 20 frames needed when the face was lost.
- **23–34 s:** no face, and the count reset.
- **35.6 s, back in view:** the face got the **same id, `visitor_1`**, so embedding re-association worked on the real camera after ~10 s away. It counted as stable at once (the gate stays passed for the encounter). The cluster settled again as `group_2`.
- **52.9 s:** `fired=yes`, `group_known`, solo, adult 0.72, ratio 0.22.
- **Then:** writing `--out` failed with `FileNotFoundError` because the directory was gone, and the impression was lost. That is a harness error, not a perception error, but it exposed a real gap: a failed `--out` write lost an already-built impression. Fixed afterwards: the impression now goes to stdout with exit code 2.

Nothing was written anywhere by the run: the torch cache and the repo were untouched, and the only files written in that window were Slack's and YouTube Music's. `take.sh` now refuses to start while the camera is busy and never deletes a folder that has files in it.

<details><summary>stderr, exactly as printed (code at a59cf54)</summary>

```
[   0.0s] fired=no 1 face(s) visitor_1:unsure(0.48) streak=1 conf=0.6 ratio=0.26 unstable group=unknown/no_track engage=idle
[   1.4s] fired=no 1 face(s) visitor_1:unsure(0.47) streak=3 conf=1.0 ratio=0.26 unstable group=unknown/no_track engage=idle
[   2.4s] fired=no 1 face(s) visitor_1:unsure(0.49) streak=4 conf=1.0 ratio=0.27 unstable group=unknown/no_track engage=idle
[   3.4s] fired=no 1 face(s) visitor_1:unsure(0.51) streak=5 conf=1.0 ratio=0.26 stable group=unknown/settling engage=counting
[   4.5s] fired=no 1 face(s) visitor_1:unsure(0.51) streak=6 conf=1.0 ratio=0.25 stable group=unknown/settling engage=counting
[   5.5s] fired=no 1 face(s) visitor_1:unsure(0.54) streak=7 conf=1.0 ratio=0.29 stable group=group_1 engage=counting
[   7.5s] fired=no 1 face(s) visitor_1:adult(0.61) streak=9 conf=1.0 ratio=0.28 stable group=group_1 engage=counting
[   8.5s] fired=no 1 face(s) visitor_1:adult(0.65) streak=10 conf=1.0 ratio=0.28 stable group=group_1 engage=counting
[   9.5s] fired=no 1 face(s) visitor_1:adult(0.67) streak=11 conf=1.0 ratio=0.31 stable group=group_1 engage=counting
[  10.7s] fired=no 1 face(s) visitor_1:adult(0.69) streak=12 conf=1.0 ratio=0.22 stable group=group_1 engage=counting
[  12.6s] fired=no 1 face(s) visitor_1:adult(0.73) streak=14 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  13.6s] fired=no 1 face(s) visitor_1:adult(0.72) streak=15 conf=1.0 ratio=0.29 stable group=group_1 engage=counting
[  14.8s] fired=no 1 face(s) visitor_1:adult(0.70) streak=16 conf=1.0 ratio=0.29 stable group=group_1 engage=counting
[  15.8s] fired=no 1 face(s) visitor_1:adult(0.70) streak=17 conf=1.0 ratio=0.28 stable group=group_1 engage=counting
[  17.8s] fired=no 1 face(s) visitor_1:adult(0.71) streak=19 conf=1.0 ratio=0.29 stable group=group_1 engage=counting
[  18.8s] fired=no 1 face(s) visitor_1:adult(0.72) streak=20 conf=1.0 ratio=0.25 stable group=group_1 engage=counting
[  19.9s] fired=no 1 face(s) visitor_1:adult(0.70) streak=21 conf=1.0 ratio=0.28 stable group=group_1 engage=counting
[  20.9s] fired=no 1 face(s) visitor_1:adult(0.69) streak=22 conf=1.0 ratio=0.21 stable group=group_1 engage=counting
[  21.9s] fired=no 1 face(s) visitor_1:adult(0.69) streak=23 conf=1.0 ratio=0.24 stable group=group_1 engage=counting
[  25.6s] fired=no 0 face(s) 
[  26.6s] fired=no 0 face(s) 
[  27.6s] fired=no 0 face(s) 
[  28.6s] fired=no 0 face(s) 
[  29.6s] fired=no 0 face(s) 
[  30.6s] fired=no 0 face(s) 
[  31.7s] fired=no 0 face(s) 
[  32.8s] fired=no 0 face(s) 
[  33.8s] fired=no 0 face(s) 
[  35.6s] fired=no 1 face(s) visitor_1:adult(0.76) streak=3 conf=1.0 ratio=0.26 stable group=unknown/no_track engage=counting
[  36.6s] fired=no 1 face(s) visitor_1:adult(0.80) streak=4 conf=1.0 ratio=0.26 stable group=unknown/no_track engage=counting
[  38.6s] fired=no 1 face(s) visitor_1:adult(0.87) streak=6 conf=1.0 ratio=0.22 stable group=unknown/settling engage=counting
[  39.7s] fired=no 1 face(s) visitor_1:adult(0.90) streak=7 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  40.7s] fired=no 1 face(s) visitor_1:adult(0.91) streak=8 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  42.7s] fired=no 1 face(s) visitor_1:adult(0.86) streak=10 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  43.8s] fired=no 1 face(s) visitor_1:adult(0.84) streak=11 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  44.8s] fired=no 1 face(s) visitor_1:adult(0.81) streak=12 conf=1.0 ratio=0.23 stable group=group_2 engage=counting
[  46.8s] fired=no 1 face(s) visitor_1:adult(0.76) streak=14 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  47.8s] fired=no 1 face(s) visitor_1:adult(0.75) streak=15 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  48.8s] fired=no 1 face(s) visitor_1:adult(0.75) streak=16 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  49.9s] fired=no 1 face(s) visitor_1:adult(0.74) streak=17 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  50.9s] fired=no 1 face(s) visitor_1:adult(0.73) streak=18 conf=1.0 ratio=0.23 stable group=group_2 engage=counting
[  51.9s] fired=no 1 face(s) visitor_1:adult(0.73) streak=19 conf=1.0 ratio=0.22 stable group=group_2 engage=counting
[  52.9s] fired=yes 1 face(s) visitor_1:adult(0.72) streak=20 conf=1.0 ratio=0.22 stable group=group_2 engage=engaged
[  52.9s] ENGAGE ('visitor_1',) reason=group_known group=GroupContext(group_id='group_2', group_size=1, has_child_band_member=False, status='known', reason='')
192 frames; max face-box ratio (enter_ratio 0.20): visitor_1=0.308
Traceback (most recent call last):
  File "/usr/lib/python3.10/runpy.py", line 196, in _run_module_as_main
    return _run_code(code, main_globals, None,
  File "/usr/lib/python3.10/runpy.py", line 86, in _run_code
    exec(code, run_globals)
  File "/home/jay/Desktop/2026-Jay/hri-museum-guide/perception/run_encounter.py", line 179, in <module>
    sys.exit(main())
  File "/home/jay/Desktop/2026-Jay/hri-museum-guide/perception/run_encounter.py", line 171, in main
    with open(args.out, "w") as f:
FileNotFoundError: [Errno 2] No such file or directory: 'si.json'
Error in sys.excepthook:
Traceback (most recent call last):
  File "/usr/lib/python3/dist-packages/apport_python_hook.py", line 76, in apport_excepthook
    binary = os.path.realpath(os.path.join(os.getcwd(), sys.argv[0]))
FileNotFoundError: [Errno 2] No such file or directory

Original exception was:
Traceback (most recent call last):
  File "/usr/lib/python3.10/runpy.py", line 196, in _run_module_as_main
    return _run_code(code, main_globals, None,
  File "/usr/lib/python3.10/runpy.py", line 86, in _run_code
    exec(code, run_globals)
  File "/home/jay/Desktop/2026-Jay/hri-museum-guide/perception/run_encounter.py", line 179, in <module>
    sys.exit(main())
  File "/home/jay/Desktop/2026-Jay/hri-museum-guide/perception/run_encounter.py", line 171, in main
    with open(args.out, "w") as f:
FileNotFoundError: [Errno 2] No such file or directory: 'si.json'
```

</details>

### Take 1b, alone: walk up, stand still, 120 s. **Fired**

- **4.2 s:** a face appears, `unsure` 0.69, ratio 0.34.
- **7.3 s:** it passes the 5-frame gate; band `adult` 0.63; engagement counting.
- **10.5 s:** cluster `group_1`, a known solo.
- **26.8 s:** `fired=yes`, `group_known`, adult 0.80. That is 22.6 s after first appearing; 122 frames; peak ratio 0.367.

**Output folder after the take:** `si.json` only (562 bytes): no frames, no embeddings, no names. It validated against Joey's schema before it was written. `p_child` rounds to 0.0; the rest of the mass is FairFace's 10–19 bin. Other files written in that window: Obsidian, YouTube Music and Slack only.

<details><summary>stderr, exactly as printed (code at a59cf54)</summary>

```
[   0.0s] fired=no 0 face(s) 
[   1.1s] fired=no 0 face(s) 
[   2.1s] fired=no 0 face(s) 
[   3.1s] fired=no 0 face(s) 
[   4.2s] fired=no 1 face(s) visitor_1:unsure(0.69) streak=2 conf=0.8 ratio=0.34 unstable group=unknown/no_track engage=idle
[   5.2s] fired=no 1 face(s) visitor_1:unsure(0.68) streak=3 conf=1.0 ratio=0.31 unstable group=unknown/no_track engage=idle
[   6.2s] fired=no 1 face(s) visitor_1:unsure(0.66) streak=4 conf=1.0 ratio=0.30 unstable group=unknown/no_track engage=idle
[   7.3s] fired=no 1 face(s) visitor_1:adult(0.63) streak=5 conf=1.0 ratio=0.29 stable group=unknown/settling engage=counting
[   8.4s] fired=no 1 face(s) visitor_1:adult(0.62) streak=6 conf=1.0 ratio=0.29 stable group=unknown/settling engage=counting
[  10.5s] fired=no 1 face(s) visitor_1:adult(0.66) streak=8 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  11.5s] fired=no 1 face(s) visitor_1:adult(0.66) streak=9 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  12.5s] fired=no 1 face(s) visitor_1:adult(0.69) streak=10 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  13.6s] fired=no 1 face(s) visitor_1:adult(0.70) streak=11 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  14.6s] fired=no 1 face(s) visitor_1:adult(0.71) streak=12 conf=1.0 ratio=0.26 stable group=group_1 engage=counting
[  15.6s] fired=no 1 face(s) visitor_1:adult(0.74) streak=13 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  16.6s] fired=no 1 face(s) visitor_1:adult(0.76) streak=14 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  17.7s] fired=no 1 face(s) visitor_1:adult(0.76) streak=15 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  18.7s] fired=no 1 face(s) visitor_1:adult(0.76) streak=16 conf=1.0 ratio=0.26 stable group=group_1 engage=counting
[  20.7s] fired=no 1 face(s) visitor_1:adult(0.76) streak=18 conf=1.0 ratio=0.28 stable group=group_1 engage=counting
[  21.7s] fired=no 1 face(s) visitor_1:adult(0.76) streak=19 conf=1.0 ratio=0.26 stable group=group_1 engage=counting
[  23.7s] fired=no 1 face(s) visitor_1:adult(0.79) streak=21 conf=1.0 ratio=0.26 stable group=group_1 engage=counting
[  24.7s] fired=no 1 face(s) visitor_1:adult(0.80) streak=22 conf=1.0 ratio=0.28 stable group=group_1 engage=counting
[  25.7s] fired=no 1 face(s) visitor_1:adult(0.79) streak=23 conf=1.0 ratio=0.27 stable group=group_1 engage=counting
[  26.8s] fired=yes 1 face(s) visitor_1:adult(0.80) streak=24 conf=1.0 ratio=0.27 stable group=group_1 engage=engaged
[  26.8s] ENGAGE ('visitor_1',) reason=group_known group=GroupContext(group_id='group_1', group_size=1, has_child_band_member=False, status='known', reason='')
122 frames; max face-box ratio (enter_ratio 0.20): visitor_1=0.367
```

</details>

`si.json` (the only file in the output folder):

```json
{"type":"start_impression","t":26.765,"visitors":[{"track_id":"visitor_1","age_class":"adult","age_conf":0.797,"cluster_id":"group_1","baseline_seed":{"distance_m":2.2,"robot_glances_per_min":4.0,"speech_frac":0.05},"pending_layers":[],"responded_to_steer_invite":false,"age_band":"adult","p_child":0.0,"p_adult":0.797}],"group":{"size":1,"spread_m":1.96},"placeholder_fields":["group.spread_m","visitors[].baseline_seed.distance_m","visitors[].baseline_seed.robot_glances_per_min","visitors[].baseline_seed.speech_frac","visitors[].responded_to_steer_invite"]}
```

### Take 2, walk across, 60 s. **Aborted**

Jay stopped it with `q` in the window before crossing. No face passed `filter_faces`. 426 frames in 18.6 s (~23 fps with no face). Output folder empty. This log could not tell "not detected" from "detected but filtered out"; that gap led to the `raw=` output (commit `a3653fd`).

<details><summary>stderr, exactly as printed (code at a59cf54)</summary>

```
[   0.0s] fired=no 0 face(s) 
[   1.0s] fired=no 0 face(s) 
[   2.1s] fired=no 0 face(s) 
[   3.1s] fired=no 0 face(s) 
[   4.1s] fired=no 0 face(s) 
[   5.1s] fired=no 0 face(s) 
[   6.1s] fired=no 0 face(s) 
[   7.2s] fired=no 0 face(s) 
[   8.2s] fired=no 0 face(s) 
[   9.2s] fired=no 0 face(s) 
[  10.2s] fired=no 0 face(s) 
[  11.2s] fired=no 0 face(s) 
[  12.3s] fired=no 0 face(s) 
[  13.3s] fired=no 0 face(s) 
[  14.3s] fired=no 0 face(s) 
[  15.3s] fired=no 0 face(s) 
[  16.4s] fired=no 0 face(s) 
[  17.4s] fired=no 0 face(s) 
[  18.5s] fired=no 0 face(s) 
[  18.6s] stopped from the live view (q)
426 frames; max face-box ratio (enter_ratio 0.20): no face passed filter_faces
no engagement event; no start_impression
```

</details>

### Raw-detection smoke test, 6 s

Two small faces at ratio 0.07–0.10 are always in view (the background). `filter_faces` drops them because they are under the 0.18 height floor. Output folder empty.

<details><summary>stderr, exactly as printed (code at a3653fd)</summary>

```
[   0.0s] fired=no raw=1[0.07] 0 face(s) 
[   1.0s] fired=no raw=2[0.10 0.08] 0 face(s) 
[   2.2s] fired=no raw=2[0.09 0.08] 0 face(s) 
[   3.3s] fired=no raw=2[0.10 0.08] 0 face(s) 
[   4.3s] fired=no raw=2[0.09 0.08] 0 face(s) 
[   5.3s] fired=no raw=1[0.08] 0 face(s) 
163 frames; max face-box ratio (enter_ratio 0.20): no face passed filter_faces
max raw MTCNN face ratio before filter_faces (height floor 0.18): 0.102
no engagement event; no start_impression
```

</details>

### Take 2b, walk across without stopping, 60 s. **No event (expected)**

- **Whole take:** two background faces at 0.07–0.11, always filtered out.
- **~16.5–21.5 s, Jay crossing:** two ids. `visitor_1` peaked at 0.256 between printed lines. `visitor_2` was at 0.20–0.22 from 17.6 s to 20.8 s, passed the gate at 19.7 s and started counting.
- **21.8 s:** gone; about 2–3 of 20 dwell frames counted.

**Highest ratio reached: 0.256**, above enter_ratio 0.20. Nothing fired because of dwell time, not distance.

The two ids are probably one person split in two: a moving box loses IoU, and a side-on face matches the embedding poorly. That is inferred, not verified. 1142 frames in 60 s. Output folder empty. Other files written in that window: Slack only.

<details><summary>stderr, exactly as printed (code at a3653fd)</summary>

```
[   0.0s] fired=no raw=2[0.09 0.08] 0 face(s) 
[   1.0s] fired=no raw=1[0.08] 0 face(s) 
[   2.0s] fired=no raw=2[0.10 0.08] 0 face(s) 
[   3.0s] fired=no raw=2[0.09 0.07] 0 face(s) 
[   4.1s] fired=no raw=2[0.10 0.07] 0 face(s) 
[   5.1s] fired=no raw=2[0.09 0.07] 0 face(s) 
[   6.2s] fired=no raw=2[0.10 0.07] 0 face(s) 
[   7.2s] fired=no raw=2[0.09 0.07] 0 face(s) 
[   8.2s] fired=no raw=2[0.09 0.08] 0 face(s) 
[   9.2s] fired=no raw=2[0.11 0.09] 0 face(s) 
[  10.3s] fired=no raw=2[0.11 0.09] 0 face(s) 
[  11.3s] fired=no raw=1[0.11] 0 face(s) 
[  12.3s] fired=no raw=1[0.11] 0 face(s) 
[  13.3s] fired=no raw=2[0.11 0.09] 0 face(s) 
[  14.4s] fired=no raw=2[0.11 0.10] 0 face(s) 
[  15.4s] fired=no raw=2[0.10 0.10] 0 face(s) 
[  16.4s] fired=no raw=1[0.10] 0 face(s) 
[  17.6s] fired=no raw=2[0.20 0.10] 1 face(s) visitor_2:unsure(0.63) streak=3 conf=1.0 ratio=0.20 unstable group=unknown/no_track engage=idle
[  18.6s] fired=no raw=3[0.22 0.10 0.10] 1 face(s) visitor_2:unsure(0.60) streak=4 conf=1.0 ratio=0.22 unstable group=unknown/no_track engage=idle
[  19.7s] fired=no raw=2[0.22 0.11] 1 face(s) visitor_2:adult(0.60) streak=5 conf=1.0 ratio=0.22 stable group=unknown/settling engage=counting
[  20.8s] fired=no raw=2[0.22 0.10] 1 face(s) visitor_2:adult(0.65) streak=6 conf=1.0 ratio=0.22 stable group=unknown/settling engage=counting
[  21.8s] fired=no raw=3[0.13 0.10 0.10] 0 face(s) 
[  22.8s] fired=no raw=2[0.13 0.09] 0 face(s) 
[  23.9s] fired=no raw=2[0.09 0.09] 0 face(s) 
[  24.9s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  25.9s] fired=no raw=2[0.09 0.07] 0 face(s) 
[  27.0s] fired=no raw=2[0.10 0.07] 0 face(s) 
[  28.0s] fired=no raw=2[0.09 0.07] 0 face(s) 
[  29.0s] fired=no raw=1[0.07] 0 face(s) 
[  30.2s] fired=no raw=2[0.10 0.07] 0 face(s) 
[  31.2s] fired=no raw=2[0.10 0.08] 0 face(s) 
[  32.2s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  33.2s] fired=no raw=1[0.08] 0 face(s) 
[  34.3s] fired=no raw=2[0.10 0.08] 0 face(s) 
[  35.3s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  36.4s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  37.4s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  38.4s] fired=no raw=2[0.10 0.08] 0 face(s) 
[  39.5s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  40.5s] fired=no raw=2[0.10 0.08] 0 face(s) 
[  41.5s] fired=no raw=2[0.10 0.08] 0 face(s) 
[  42.5s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  43.5s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  44.5s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  45.6s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  46.7s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  47.7s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  48.8s] fired=no raw=1[0.08] 0 face(s) 
[  49.8s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  50.8s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  51.9s] fired=no raw=2[0.09 0.08] 0 face(s) 
[  52.9s] fired=no raw=2[0.10 0.07] 0 face(s) 
[  53.9s] fired=no raw=1[0.10] 0 face(s) 
[  55.0s] fired=no raw=1[0.10] 0 face(s) 
[  56.0s] fired=no raw=0[] 0 face(s) 
[  57.0s] fired=no raw=1[0.09] 0 face(s) 
[  58.1s] fired=no raw=0[] 0 face(s) 
[  59.1s] fired=no raw=1[0.09] 0 face(s) 
1142 frames; max face-box ratio (enter_ratio 0.20): visitor_1=0.256, visitor_2=0.246
max raw MTCNN face ratio before filter_faces (height floor 0.18): 0.256
no engagement event; no start_impression
```

</details>

## Our start impression inside Joey's scenarios (Part 3, Level 1)

```
python3 -m perception.integration.run_in_scenario --seeds 20 --out perception/integration/results.md   # ~2.5 min
```

Test scaffolding in `perception/integration/`, not product code.

**What the script does, for each scenario and seed:**
1. It builds a fake encounter scene from Joey's six visitors and runs our real `Encounter` on it.
2. It maps our ids to his (`visitor_k` → `vN`) by matching boxes at the event. That mapping exists only here.
3. It swaps his `start_impression` line for ours, and then his own code runs:
   - **s1_one_stop (open loop):** his stream comes from `sdc.mock.generate`, with line 2 replaced. `SignalLayer` and `eval_signals.evaluate` then run on it.
   - **s1_closed and s2_multi_stop (closed loop):** `sdc.sim.Sim.start_lines` is replaced inside this process only and restored in a `finally`. His `run_closed_loop` and `run_tour` then run with the same factories as `compare_policies.run_s1` / `run_s2` (policy `ours`).
4. Tables are formatted with his `compare_policies.row` / `summarise` / `table`.

No file under `sdc/`, `data/` or his root scripts is edited, and no threshold changed.

**Tests** (`perception/tests/test_integration.py`):
- Condition A reproduces `compare_policies.run_s1` / `run_s2` and the unspliced open-loop events exactly. A check confirmed the equality fails for B.
- `start_lines` is restored even when the run raises.
- Our impression covers exactly his six visitors and validates.

**Fake-scene assumptions.** These are my choices, and they decide our clusters:
- **Frame:** 1280 × 400 px.
- **Order:** left to right in his visitor order (v1…v6). Companions are adjacent in that order: c1 = v1, c2 = v2 + v3, c3 = v4, c4 = v5 + v6.
- **Face size:** adults 80 px wide (height = 1.2 × width). **The child's face is 0.85 × an adult's.**
- **Spacing:** **companions 0.3 face widths apart, clusters 2.5 face widths apart.** Our clustering joins faces within 1.5 widths.
- **Movement:** everyone walks up together (faces grow from 0.5× to full size in 3 s), then stands still.
- **Embeddings:** seeded per person, with small per-frame noise.
- **Age estimator outputs:** adult (0.05, 0.93, 0.02), child (0.88, 0.08, 0.04), unsure (0.20, 0.35, 0.45), each with ±0.03 seeded jitter.

**Conditions** (20 seeds each, all three scenarios):

| Condition | Start impression |
|---|---|
| **A** | his own |
| **B** | ours, ages right |
| **C-v1, C-v3, C-v4, C-v5, C-v6** | ours, that adult read as a child |
| **C2** | ours, the child v2 read as an adult |
| **D** | ours, v2 unsure |
| **D-all** | ours, all six unsure |
| **B+his distance_m**, **B+his cluster_id** (diagnostics) | B with that one field copied back per visitor, to split effect (i) |

**Results** (full tables and per-visitor events in `perception/integration/results.md`):

- **(i) Placeholder seeds and clusters, B vs A:**
  - **s1_one_stop and s1_closed: v2 (the excluded child) is detected later.**
    - Open loop: excluded latency 3.6 s → 11.5 s; bid latency 3.6 s → 13.1 s, with 12 extra unlabelled bid detections over 20 seeds (bid precision 1 → 0.72 [0.33–1.00]).
    - Closed loop: v2's first bid/excluded moves from 53.6 s to 62.0 s (+8.4 s); exclusion episodes 2 → 1.90 [1–2]; time to resolve 2.38 → 2.50 [2.00–4.00]. P13 stays 0.
  - **s2_multi_stop: no difference at all.**
  - **The cause is the placeholder `distance_m`, not our clusters.** With his distances copied back, every measure and every per-visitor event equals A. With his clusters copied back, nothing changes compared with B.
  - **Mechanism, read from the event reasons:** v2 starts 3.0 m from the exhibit, but our seed says 2.2 m and counts as 30 s of observation. When v2 edges in at 50–60 s, the move isn't "closer than own baseline", so the edging-in bid that fires at 53–54 s in A is missed. The bid then comes from the glance cue (56–57 s) or only from being talked over (73 s, seed 3).
  - **Why s2 shows nothing:** in s2, v2 starts *inside* the formation, so the seed only sets the in-formation baseline. The excluded episode at stop 2 uses an unseeded out-of-formation baseline.
- **(ii) Age errors, C-\* and C2 vs B: no visitor's events differ in any scenario, and every measure is identical.** The glance seed does reach his loop (v2's own glance baseline is 3.5/min in B, 2.8 in C2). But v2's glance burst is 12/min, far above `GLANCE_RATE_FACTOR` (1.5) × either, so `GLANCE_MIN_SHORT` = 2 short glances in 10 s decides the timing. Adults never produce glance bids in these scenarios.
- **(iii) Unsure, D and D-all vs B: no difference anywhere,** for the same reason.
- **Our clusters at the event split his companion pairs.** In all 540 encounters the result was the same: v1 and v4 got known groups, but v2, v3, v5 and v6 got `solo_…` clusters.
  - **Why:** the event fires when the first visitor's group is known. Lone visitors are known after `stable_s` (1.5 s), but pairs need `together_s` (3 s), so the impression, which is a snapshot at the first event, never contains a pair.
  - **Effect:** his loop's measures didn't change, because a cluster only sets which way the robot faces for an addition. But it is a real limitation of taking the snapshot at the first event. Not changed.

**What this can and cannot show.** It shows how our start impression's choices change Joey's loop on his scripted, rule-based visitors. It shows nothing about real visitors or real-camera clustering of real groups. The fake scene is my construction, and the age effects can only show up where his scenarios contain the behaviour the seeds gate.

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
- **Docs** (`63627b0`). This added this README and `INTERFACE_NOTES.md`.
- **H, webcam run:**
  - **Progress output:** `86fee25` added `fired=` and the max ratio printed at exit; `a59cf54` added `--show`; `a3653fd` added the raw MTCNN faces (`raw=`). All three change display only; no threshold changed.
  - **Takes, 2026-11-17:** a setup check; take 1a (fired; JSON lost to a harness error); take 1b (fired, `si.json` only); take 2 (aborted); take 2b (no event). Two-person take 3 was not run. Details are below.
- **`--out` fix** (`0d8ba64`): a failed `--out` write now prints the impression to stdout and exits 2, with no fallback file. New test.
- **Profile format** (`4e3640c`): `PROFILE_FORMAT.md`.
- **Part 3, Level 1** (this commit): `perception/integration/run_in_scenario.py`, `results.md` and `tests/test_integration.py`. Every check passed: 99 tests in `run_tests.py` (both venvs) and 93 perception tests.
