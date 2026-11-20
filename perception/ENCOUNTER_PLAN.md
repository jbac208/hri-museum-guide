# Encounter phase for the simulation and replay: inventory and plan

Branch `jay/encounter-sim` (from `jay/perception` at `4ab7e52`). Written 2026-11-18, approved by Jay the same day with every default in the decisions table. Everything under "Read/ran" was read or run on this date.

## Status (2026-11-18): built, apart from F's third condition

- **Built as planned:** sections A to E and G. How to run it: `perception/README.md`, section "Encounter phase in the simulation and replay".
- **The draft video** (`replay/s2_multi_stop_encounter.mp4`, 127 s, 1440×1260, gitignored) is rendered automatically (with sound since 2026-11-19) by `python3 -m perception.encounter_sim.video`, using headless Chrome plus ffmpeg, not a screen capture.

**Follow-up (2026-11-19), after Jay's request:** the encounter is slower and starts at a reception, not at stop 1.
- Visitors come in through an entrance at 0.8 m/s (was 1.2), 2.0/2.6 s apart (was 1.5/1.2), and the robot greets after 4 s with no new face (`run.GATHER_S`, was 3).
- The reception is stop 1's formation moved 7 m south (`scene.RECEPTION`). After the lead-in ("Let's head over to the ship's figurehead. Please follow me.", `dialogue.LEAD`) the robot walks to its stop-1 spot at 0.7 m/s and the visitors follow; the handoff is at the end of that walk, so t = 0 starts the tour as before. About 74 s in all.
- The video has speech sound (gTTS, `audio.py`; online, cached) for every line, encounter and tour (speech at 1x, silent stretches at 4x).
- Companion groups appear step by step as perception settles them (`encounter: cluster update` notes), all settled before the greeting. **Open:** also using conversation as a cluster signal (Jay's suggestion, 2026-11-19); not built, needs a design decision (see Jay's decisions in the reply of that day: privacy and D4).
- Visitors are lively in the encounter (`scene.Gaze`, his sim's noise), as in the tour.
- **Follow-up 2 (2026-11-19):** a welcome, an introduction and three icebreaker questions (tour before? day? favourite exhibit?) before the LLM's questions (`dialogue.ICE`, scripted, no LLM); one profile per visitor shown from the encounter through the tour (seeded layers dated when said); sound for the whole tour, including the simulated visitors' questions (his scenario's text, added as `tour: visitor said` notes). **Open:** nothing in his tour reads `prior_tour`; his decision code would have to (his call, not edited here).
- **Follow-up 3 (2026-11-20):** "museum tour" wording (greeting, intro, favourite question; the LLM menu's open question still says "gallery": changing it needs a re-recording). The robot leads the group to the figurehead straight after the small talk; the LLM's two tour questions are off by default (`--tour-questions`). Encounter about 114 s. **Open:** the only seeded guess (v3 compass) is never tested by his tour (pending layers score 0.15, see README).

**Changes from the plan below, found while building:**
1. **When the robot greets.** The engagement event fires for the first arrival alone (v1, about 9 s before the group is complete). So the robot greets only once:
   - everyone in view has passed the stable gate;
   - every companion cluster is known;
   - no new face has appeared for 3 s (`run.GATHER_S`).

   The arrivals are tighter than first planned (`scene.GAP_SAME`/`GAP_NEXT` = 1.5/1.2 s), so that no 3 s lull falls between faces.
2. **Ids.** Staggered arrivals alone gave v1…v6, with no fallback needed. The runtime guard is in place.
3. **A guard rule added after the first real-LLM run.** `qwen2.5:7b` filed "Short is fine." under the only depth option ("the full story"), with a verbatim quote and confidence 0.8, for two visitors. A quote must now also *name* the option: its name, its id, or a listed paraphrase (`dialogue._cues`). The recorded run's error is caught and shown in the replay ("dropped: depth:figurehead (quote_does_not_name_it)").
4. **Two recording runs, 14 local calls in all.** The extra run was needed because the next-question prompt includes what has been learned so far, and that changed once the guard dropped the bad items. The first recording is not in the repo.
5. **F was run now** (`perception/encounter_sim/check.md`), with two conditions; the third (wrong extractions) was not. With the conversation's layers:
   - 8/20 seeds go to the compass instead of the ship model at stop 2 (14/20 after follow-up 2 added the icebreakers' favourite-exhibit layers);
   - uptake 0.72 → 0.62, misread 0 → 0.10 (0.72 → 0.58 and 0 → 0.12 after follow-up 2);
   - P13 0 in both;
   - no extra non-routine robot actions toward v4.

   **The recorded video run (seed 1) is one of the compass seeds**, so stop 2 in the video is the compass, and the child's scripted exclusion happens there. A seed with his route (for example seed 2) needs its own recording: about 7 more local LLM calls.
6. **Records.** The encounter's answers and handoff go in `note` records, not new record types: `make_replay.build()` passes only known types to the page, and this needs no edit to it.

## 0. What exists

### 0.1 Replay UI (Joey's)

| Piece | File and function | What it does | Reuse? |
|---|---|---|---|
| Builder | `make_replay.py` `records_for(name)` | Runs a scenario and returns `(loop.end_tour() records, sim.reactions)`. `s2_multi_stop` goes through `run_tour.run`, `s1_closed` through `run_sim.run`, `s1_one_stop` through `run_loop.run` | Yes, as is |
| | `make_replay.py` `build(records, sim)` | Groups records by `type` (`meta`, `track`, `event`, `action`, `note`, `profile`, last `measures`), adds `data/gallery.json` and the sim reactions, and pastes the JSON over `/*DATA*/null` in the template. The output is one self-contained HTML file | Yes, as is: new record types pass through |
| | `make_replay.py` `main()` | Options `scenario`, `--log`, `--anon`, `--out` | Needs a flag or a wrapper (see E) |
| Data source | `sdc/metrics.py` `EventLog` | `track` records at `LOG_TRACK_HZ` = 5 (robot pose plus per-visitor `id, x, y, body_yaw, head_yaw, attention, speaking, in_formation, los_exhibit, cluster`). `records()` adds `event`, `profile` (the profile store log), `action` and `note` (the decision log), and `plan` notes, then `measures`. `end_tour()` passes everything through `redact_speech` (quoted visitor speech becomes `"[speech]"`, Q13) | Encounter records use the same shapes |
| Map | `viz/replay_template.html` `drawMap(t)` | Metre grid; formation ring (r 1.8, width 1.6) around the current stop; exhibits and features; dashed line when the view is blocked; robot gaze line; visitors as discs coloured by **cluster** (`clusterOf` from `tracks[0]`), filled when in formation, with head-yaw tick, id label, 💬 and event badges; robot triangle from `robotAt(t)` (first track plus `turn_body`/`step_to` actions). One camera per stop and per move (`camWins`/`views`) | Extend: encounter camera, undetected visitors, cluster ring, age badge |
| Timeline | `drawTimeline()` | Stop segments from `stop start` / `transition start` notes. Robot lane: `say_to_group` bars coloured by `sayType` (`core`/`add`/`qa`/`open`); other actions as ticks; exclusion fixes in red. One lane per visitor: events, ✓/✗ uptake notes, sim-reaction circles. **Time axis is `tx(t) = LEFT + t / T_END · width`, from 0** | Extend: axis from a negative start, "0. Encounter" segment |
| "Robot says" | `drawPanel()` `sayingAt(t)` | Text of the `say_to_group` action active at `t`, with its type tag | Works for encounter speech unchanged; add a "Visitors say" line |
| Profile layers | `layersAt(t)` | Latest `profile` entry per layer id up to `t` (pending dashed, confirmed green, rescinded struck through) plus credit weight `w` | Works unchanged: pending layers from the start impression already appear at 0 s |
| Live measures | `drawMeasures()` | Final `measures` record (D3, D10, D6, D8, P13, falling behind, per-stop uptake) | Unchanged (tour only) |
| Controls | playback block | Space, arrows, scrubber (`min` 0), `?t=`, "Export map" (SVG) | Scrubber minimum needs to go negative |

Ran: `python3 make_replay.py s2_multi_stop` wrote `replay/s2_multi_stop.html` (2230 KB; `replay/` is gitignored). Headless Chrome (`--headless=new`, local file) rendered it at `?t=160`: header "s2_multi_stop · Ship's figurehead → Ship model → Sailor's sea chest · 390.4 s · 6 visitors"; clock "160.0 s"; v2 shown excluded with a bid; turn_body for the exclusion fix; measures panel filled. Screenshot: `/tmp/claude-1001/-home-jay-Desktop-2026-Jay/c0755f9f-1ceb-4a57-ab13-a0396bc413f0/scratchpad/replay_s2_t160.png`.

### 0.2 Simulation (Joey's)

| Piece | File and function | What it does | Reuse? |
|---|---|---|---|
| Frame generator | `sdc/mock.py` `World` | Builds schema-v0.1 frames from `VisitorScript`s. Positions come from keyframed `path`s. Gaze comes from `_GazeProcess` (`gaze_mix`, scripted `Window`s). Line of sight, formation ring `FORMATION_RING` (1.0, 2.6) and `overlapped` are derived. Frame `cluster_id` and `age_class` come from the script | Yes, unchanged |
| Start impression | `World.start_lines()` | Emits `header` plus **one `start_impression` at t = 0.0**: per visitor `age_class`, `age_conf`, `cluster_id`, `baseline_seed{distance_m` = true distance to the exhibit at t = 0, `robot_glances_per_min` 6 for a child / 4 for an adult, `speech_frac` 0.05}, `pending_layers` (from `VisitorScript.pending_layers`, always `[]` in his scenarios), `responded_to_steer_invite` | This is where the encounter's output goes |
| One-stop sim | `sdc/sim.py` `Sim`, `run_closed_loop` | Closed loop. On `say_to_group` with `.add.`, `_react_to_addition` lets each visitor take it up with `P_UPTAKE_MATCH` 0.85 if the addition's `serves` matches a **hidden interest**, otherwise `P_UPTAKE_OTHER` 0.05. On `widen the formation` or an exclusion gaze, `_react_to_opening` moves the visitor to `join_xy`. Questions are `SimSpeech` items: `at`, `gap` (waits for the robot to be quiet) or `interrupt` (the child) | Unchanged |
| Tour sim | `sdc/sim.py` `TourSim`, `TourVisitor`, `run_tour` | Visitors follow the robot. Per-stop windows, moves, joins and speech start at the robot's `arrange:` turn. `_react_to_choice` turns visitors with a matching `exhibit_interest` toward an option. **t = 0 is the start of stop 1:** visitors are already standing at their slots (`path=[(0, x, y)]`) and the robot is at `ROBOT_STOP_OFFSET` (−2.2, −0.3). The tour's first actions, from my run: `turn_body` "arrange" at 0.0 s and the first core line at 5.0 s | Unchanged; wrapped |
| Scenarios | `sdc/scenarios.py` `s1_one_stop`, `s1_closed`, `s2_multi_stop` | The same six people: v1 adult (c1), v2 child (c2), v3 adult, v2's parent (c2), v4 adult reserved (c3), v5 adult (c4), v6 adult, tired (c4) | Source of the encounter's people |

**Where the hidden ground truth lives:**
- Interests: `SimSpec.interests` (s1_closed) and `TourVisitor.interests` (s2), as `(kind, target)` sets. For s2: v1 {carving, depth figurehead, depth ship_model, compass}; v2 {sea_chest.lid, sea_chest}; v3 {paint, compass}; v4 {sea_chest}; v5 {ship_model, sea_chest}; v6 none.
- Child or adult: `age_class` on the script. This is **not hidden**: it goes into every frame and into the seed.
- Reserved or talkative: **there is no field.** It is implicit in the scripts: v4 has no speech and an exhibit-heavy `gaze_mix` (the "reserved" label in `s1_one_stop`). v3 has five `SimSpeech` items in s2, v2 has one, the others none.
- How visitors decide: uptake is a seeded draw (`spec.seed + 1`) against the hidden interests; questions are scripted (when) and gated by robot speech (`gap`/`interrupt`); nobody answers anything, because the robot never asks a question that expects one. The `open` question in the content is not answered by the sim.

**Seed fields the loop never reads** (from a grep of `sdc/` outside the schema, adapter and mock): `responded_to_steer_invite` and `age_conf`. `age_class` matters only through the glance seed (FINDINGS). `pending_layers` are loaded by `ProfileStore.load_start_impression` as pending with `SEED_LAYER_CONF` = 0.3, whatever confidence we send.

### 0.3 Profile store (Joey's)

`sdc/profile.py`:
- `VisitorProfile` holds `track_id`, `cluster_id`, `credit` and `layers`.
- A `Layer` holds `kind` (`feature_interest` / `depth` / `exhibit_interest`, which is `content.LAYER_KINDS`), `target`, `status`, `confidence` and `evidence`.

**There is no age field.** Adding one would touch:
- `VisitorProfile`, `load_start_impression` and the `_entry` log format;
- `metrics.anonymise` (it handles ids, not ages);
- his tests.

It would also put an appearance-derived value where decisions read (D4 risk). The loader does not check kind or target, so our code must.

### 0.4 Our perception

| Piece | File | What it can supply to a simulated encounter today |
|---|---|---|
| Tracker | `perception/tracker.py` `VisitTracker` | Ids `visitor_{n}` in order of first detection, plus `track_conf` |
| Stable gate | `perception/encounter.py` `STABLE_FRAMES` 5 | Who counts as present |
| Age band | `perception/age.py` `AgeBandPipeline` + `FakeAgeEstimator` (or the Part 3 `ScenarioCamera.estimate`) | `band`, `confidence`, `p_child`, `p_adult`, from **scripted** probabilities. FairFace needs pixels, and the sim has none |
| Clusters | `perception/group.py` `GroupTracker` | `GroupContext(group_id, size, has_child_band_member, status)` |
| Engagement | `perception/engagement.py` `EngagementEngine` | One `EngageEvent` (`persons`, `group_id`, `t`, `reason`); `exchange_started()` marks the people in an exchange |
| Impression | `encounter.py` `build_start_impression`, `Encounter.step/start_impression/end` | A validated `start_impression`; extra fields `age_band`, `p_child`, `p_adult` and `placeholder_fields`. `run()` returns at the first event; `step()` can continue past it |
| Fake scene, splice | `perception/integration/run_in_scenario.py` `ScenarioCamera`, `our_impression`, `replaced_start_impression` | Image-plane scene from his visitors; ids mapped to his **after the fact** by box overlap (scaffolding); his `Sim.start_lines` patched in-process and restored in a `finally` |

Ran (scratch script `/tmp/claude-1001/-home-jay-Desktop-2026-Jay/c0755f9f-1ceb-4a57-ab13-a0396bc413f0/scratchpad/cluster_later.py`; repo unchanged): the Part 3 scene with s2's six people, `Encounter.step` continued past the event, impression taken at the event and 5, 10 and 20 s later, 20 seeds.
- **At the event (3.9 s), clusters are split** as in FINDINGS: only the lone visitors are known.
- **5 s later and after, all 20 seeds have the correct partition** {v1} {v2, v3} {v4} {v5, v6}.
- **Our ids are not his ids:** visitor_6 is v2 (the child's smaller face passes `filter_faces` later), visitor_2 is v3, and so on. Ids in his order do not happen by themselves.

### 0.5 Frozen code in `HRI-2027-SDC-Museum-Guide-robot` (`museum-visual-profile`; read with `git show`, nothing changed)

| File | What carries over | What conflicts |
|---|---|---|
| `modules/museum/initiation.py` + `config/museum_initiation.yaml` | The `neutral_group` greeting ("Hello, everyone, and welcome! I'm {robot_name}, and I can show you around.") and the default first question ("Would you like the short version of each exhibit, or the full story?"). The rule that `unsure` or low confidence falls back to neutral | **D4:** the `child_*`, `adult_*` and `group_child_present` rows change wording, `speech_rate`, `approach_distance_m` and `gaze_height` by age band; D4 lets child/adult seed baselines only. Use the neutral group row only. **D7:** the `*_solo` rows are fine in wording but irrelevant to a group tour |
| `modules/museum/profiling_policy.py` + `config/museum_policy.yaml` | The question allow-list idea; choice questions before one open question; a hard question budget; the policy as pure deterministic code | **D7:** budget, pending question and "offer" are **per person** (`_P` per `pid`), and offers address one visitor. **D2:** `ignore_after_turns` turns silence into negative evidence ("ignored" → `record_style(-d)`), which presses and reads the reserved. Its dimensions (`talk_level`, `depth`, `pace`, `interest`) do not match his layer kinds; only `depth` maps. The `adapt` step duplicates his addition/uptake loop. Carry over the ideas, not the code |
| `modules/museum/profile_extraction.py` | The guard contract, nearly line for line: JSON parse (`_parse_json_object` from `modules/kg_extraction.py`, 12 lines); closed vocabulary; `CONFIDENCE_MIN` 0.6 (untuned); the verbatim-quote check; parse or shape failure applies nothing; items validated before any is applied; the text itself is not stored; the "do not infer mood, age, gender, culture" prompt line | Vocabulary must become his `(kind, target)` pairs, not `TOPIC_CATEGORIES` and style dims. It imports `modules.graph_relationship.schema` and `modules.kg_extraction`, so copy the two small helpers rather than the import. A low-confidence item is dropped on its own while the rest of the reply is applied; I keep that (see B) |
| `modules/ai_server_llm.py` | Standard library only. Length-prefixed JSON over TCP; `respond()` never raises (returns `"[LLM error: …]"`, which the guard then rejects as a parse failure) | Its own comment says the server **ignores** `json_mode`, `temperature` and `seed`, so outputs are not reproducible; that is one more reason to record and replay. It needs the lab network (`AI_HOST`, default `10.42.0.118:7898` in `live.py`) |

### 0.6 LLM access on this machine (checked without sending any request)

- **Environment:** no `ANTHROPIC_*`, `OPENAI_*`, `OPENROUTER*`, `GEMINI*`, `GROQ*`, `HF_*`, `AI_HOST` or `AI_PORT` variables are set. No `.env` exists in either repo or in `~`.
- **Python:** `openai`, `requests`, `httpx` and `transformers` are installed; `anthropic`, `ollama` and `llama_cpp` are not.
- **Ollama** (snap v0.40.2) is installed and its service is active, listening on `127.0.0.1:11434`. Model manifests on disk: `qwen2.5:7b`, `qwen2.5:14b`, `llama3.1:8b`, `nomic-embed-text`.
- **GPU:** RTX 5060, 8 GB. The 7B/8B models fit in GPU memory; 14b would partly spill to CPU (not measured).
- **Lab AI server:** this machine has `10.42.0.1` on the lab subnet. Whether `10.42.0.118:7898` is reachable was **not checked** (that would be a network call).

## A. The encounter phase in the simulation

**Time.** The encounter runs at **negative times, about −45 s to 0 s.** The handoff is at t = 0, exactly where his stream already puts the `start_impression`. The tour's own times, log and measures stay exactly as they are; only the replay's axis starts earlier.

| t (approx.) | Map (simulated world) | Our perception (real code, simulated input) | Robot |
|---|---|---|---|
| −45 to −36 | Clusters walk in from the gallery entrance to their stop-1 slots, staggered by about 1.5 s, in order v1, (v2, v3), v4, (v5, v6). Grey and unlabelled until detected | Fake camera faces grow as they approach; tracker plus stable gate; each id appears on the map when the gate passes | At the stop-1 pose, facing the entrance |
| about −34 | | Engagement event (`group_known` or `settle_timeout`) | `exchange_started`; turns to the group |
| −33 to −28 | | Clusters still settling (at the event they are split; see 0.4) | Greeting (neutral group row) |
| −27 to −3 | Visitors answer (💬) | Clusters become known (+5 s in the check above) | Questions 1–2 from the menu (B) |
| −3 to 0 | | Snapshot: `start_impression` built at the **handoff**, not at the trigger | "Thank you. Let's begin with the ship's figurehead." |
| 0 → | His tour, unchanged | | His tour |

**IDs.** In a real deployment the tour's ids *are* perception's ids, so there is nothing to map. In the sim, the simulated people need names that perception will also give them. I propose making that true by construction and checking it at runtime:
1. The tracker gets an id format option (`id_fmt`, default `"visitor_{}"`; the sim uses `"v{}"`). `encounter._num` then parses trailing digits. This is a small change in our code.
2. The scripted arrival order is v1…v6, staggered enough that each face passes `filter_faces` in that order. The child v2 starts walking early enough that it is confirmed after v1 and before v3.
3. A guard: the handoff must contain exactly {v1…v6}, and each visitor's seed must agree with the sim's script on age. Otherwise the run **fails** and nothing is silently relabelled. Ordering is not verified yet.
- Fallback if staggering does not give a stable order: build the tour spec under our ids (v2 would become, say, v6). That changes the familiar "v2 = child" naming in HANDOFF and FINDINGS.

**Clusters into the tour.** Build a copy of `scenarios.s2_multi_stop()` with each `TourVisitor.cluster_id`, `age_class` and `age_conf` set from the handoff (`dataclasses.replace`; no edit to `sdc/`). Frames then carry our clusters too, like Level 2, which changed nothing in 60/60 runs.

**`pending_layers` and the extra fields.** `TourVisitor` has no `pending_layers`, so these go in through the existing `replaced_start_impression` splice.

**`distance_m`.** Keep the placeholder 2.2 m and list it in `placeholder_fields`. FINDINGS shows **no difference in s2** under the placeholder (condition B), so the honest value costs nothing in the video scenario. If s1 is used, it delays v2 by about 8 s.

**New log entries** (records with t < 0, the same shapes as `EventLog`):
- `track` records for the encounter (5 Hz), with optional extra fields per visitor: `detected` (bool), `age_band`, `age_conf`, `group_status`. Old replays lack them and draw as now.
- `note` records:
  - `encounter: detected` (track_id)
  - `encounter: engagement` (persons, reason, group_id)
  - `encounter: clusters` (partition, status)
  - `encounter: question` (qid, how chosen: llm or fallback)
  - `encounter: answer` (track_id, qid, extracted layers, dropped items and why)
  - `encounter: handoff` (the full start impression; it contains no speech text)
- `action` `say_to_group` records with ids `encounter.greet`, `encounter.q.<qid>`, `encounter.ack`, `encounter.lead`. All of them go to the group.
- `utterance`-like records for the simulated answers (`type: "encounter_utterance"`, t, track_id, text). See decision 5 on redaction.
- An `llm` record per call: role (`select` or `extract`), the prompt's hash, the raw output, accepted or not. It also goes to the recording file (B).

## B. The first conversation with the group

**Menu** (closed, in `perception/`, built from `data/gallery.json` names at run time; wording reviewed against `content.SINGLING_OUT`):

| qid | Type | Text (to the group) | May yield |
|---|---|---|---|
| `depth` | choice | "Would you like the short version of each piece, or the full story?" (frozen default question) | `depth:<first stop>` only for "full". **"Short" yields nothing:** his vocabulary has no "less depth" |
| `features` | choice | "At our first stop, the ship's figurehead, shall I tell you more about the carving or the paint?" | `feature_interest:figurehead.carving`, `feature_interest:figurehead.paint` |
| `open` | open | "Is there anything in this gallery you're curious to see?" | `exhibit_interest:<exhibit>`, `feature_interest:<feature>` over the gallery |

Budget **2 questions per group**. Choice questions come before `open`; `open` is allowed only after at least one choice question. No question repeats.

**Policy: the LLM proposes, code decides.**
- **Selection.** Code computes the allowed qids (budget, order, not asked). The LLM gets the allowed ids plus a summary of the layers already extracted (no raw text). It returns `{"next": qid | "none"}`. Code accepts it only if it is in the allowed set. Otherwise, or on any parse failure, it takes the **first allowed qid in menu order** (logged as `fallback`).
  - Honest note: with three items and a budget of two, the LLM makes at most one real choice. The fixed order is the baseline.
- **Extraction** (per answer). The LLM gets the qid, its allowed `(kind, target)` pairs with their display names, and the utterance. It returns `{"layers":[{"kind","target","confidence","quote"}]}`. Code checks, in order:
  - Parse or shape failure → **the whole answer is dropped**.
  - Per item: `(kind, target)` must be one **of this question's** allowed pairs (tighter than the global vocabulary); confidence ≥ 0.6 (`CONFIDENCE_MIN`, untuned placeholder); `quote` must be a non-empty verbatim substring.
  - A failing item is dropped whole (never repaired, for example with a different target). Items are validated before any is applied. At most 2 per answer.
  - The prompt forbids inferring age, mood, gender, culture or anything not said.
- **What the profile receives.** A pending layer per surviving item for the speaker only. His loader fixes its confidence at 0.3 whatever we send. The LLM's confidence only gates.
- **Never** (structural, not prompt-dependent):
  - The robot cannot name anyone, ask anyone individually, follow up with a quiet visitor, or mention appearance or age: the menu is the only source of robot speech, and it is fixed text.
  - Silence creates no evidence (unlike the frozen policy's "ignored").
  - The acknowledgement is fixed: "Thank you, that helps." It never says who answered.

**Simulated replies** (no LLM): templates over each visitor's hidden interests, drawn with `random.Random(seed)`.
- **Who answers.** Each visitor gets a talkativeness level in *our* encounter script, because his sim has no such field. Proposal, consistent with his scripts:
  - v3 high (0.9)
  - v2 high (0.8; the child who interrupts later)
  - v1 medium (0.5)
  - v5 medium (0.5)
  - v6 low (0.2; tired)
  - **v4 reserved (0): never answers**

  These are invented parameters (decision 4).
- **What they say:**
  - `features`: the matching feature ("The carving!"), else "Either is fine."
  - `depth`: "The full story, please." if they have `depth:figurehead`, else "Short is fine."
  - `open`: a named exhibit from their `exhibit_interest` ("What's that chest over there?").
  - One to three answers per question, 0.5–1.5 s apart.
- Replies are **truthful by construction**. F therefore measures a best case: honest answers and correct attribution of each utterance to its speaker. In the sim the speaker's track_id comes with the utterance; on a real robot that is the open ASR and attribution question, P16.

**LLM clients** (all behind one `fn(system, user) -> str`):
- `FakeLLM`: the default for tests. Selection is the first allowed qid. Extraction matches the display names as keywords and emits the same JSON, so the guards run on the real path.
- `RecordingLLM(inner, path)`: writes `{key: sha256(model, system, user), raw}` lines.
- `ReplayLLM(path)`: reads them. **A missing key is an error**, never a silent fallback to the fake.

**Which LLM:** local **Ollama `qwen2.5:7b`**, through its HTTP API with the standard library's `urllib`, `format: "json"`, temperature 0 and a fixed seed.
- Already on disk; the service is already running.
- Fits the 8 GB GPU.
- No API keys exist here.
- The visitors' (simulated) speech never leaves the machine, which matches the privacy rule even though these visitors are fictional.
- Ollama honours JSON mode, temperature and seed, which the lab server does not.
- Qwen2.5 is reliable at structured JSON; `llama3.1:8b` is the alternative.
- The lab AI server stays an option for the robot later; its client ports as is.
- **One recording run needs your permission:** it is a request to a local LLM, about 15 calls.

## C. The handoff

The encounter writes one `start_impression` at t = 0, validated by `sdc.schema.validate_start_impression`:

| Field | Source |
|---|---|
| `track_id` | Our tracker (`v1…v6` by construction; guard in A) |
| `cluster_id` | Our `GroupTracker` at the **handoff**; `solo_<id>` if still unknown |
| `age_class`, `age_conf` (plus the extras `age_band`, `p_child`, `p_adult`) | Our age band at the handoff (scripted estimator) |
| `responded_to_steer_invite` | True if the visitor gave any answer that survived the guard. **His loop never reads this field**, so it has no effect on the tour |
| `pending_layers` | Only the guard-surviving items from what the visitor said. Never from appearance, never from silence |
| `baseline_seed` | As now: placeholders, plus the glance seed from the band |

The tour then runs unchanged.

**Age in the profile:**
- **(a) UI only (recommended).** The replay reads age from the `encounter: handoff` note. Cost: none in Joey's code. The profile store stays appearance-free, so D4 cannot drift.
- **(b) A field in `sdc/profile.py`.** Cost: edits to `VisitorProfile`, `load_start_impression` and the log format, plus `anonymise` and his tests. Any later decision code could then read age (D4 risk). Only worth it if Joey wants age in the kept log for the paper.

## D. UI changes (additive; old replays must render identically)

All in `viz/replay_template.html`. Each change is a no-op when there are no records with t < 0.
- **Time axis.** `T0 = min(0, first record t)`. `tx()`, the tick loop, `scrub.min` and `?t=` use `[T0, T_END]`.
- **Timeline.** A "0. Encounter" segment `[T0, 0)` ahead of "1. Ship's figurehead". The robot lane gets encounter speech (a new `sayType` "encounter" with its own colour). Visitor lanes get answer dots and a "detected" tick.
- **Map.** An encounter camera window (`camWins` entry over `[T0, 0)`).
  - Visitors with `detected === false` are drawn grey and unlabelled.
  - Detected visitors get their id label.
  - A **cluster ring** (one convex outline or dashed circle per known cluster, cluster colour) appears once the cluster is known.
  - A small **age-band badge** ("child? 0.88") with the legend entry "age band: internal estimate, never spoken, seeds baselines only (D4)".
  - Cluster colours come from the first track at t ≥ 0, so the colours match the tour.
- **Panel.**
  - "Robot says" works as is.
  - New line "Visitors say (simulated)" during the encounter.
  - New card **"Initial profile (handed over at 0 s)"**: per visitor the age band and confidence, the cluster, and the pending layers with the question that produced each one.
- **Flag.** `--encounter` (see E for where it lives).
- **Check.** Build `s1_one_stop`, `s1_closed` and `s2_multi_stop` without the flag before and after the edit, and diff the headless `--dump-dom` at a few `?t=` values. They must be identical.

## E. Where the code lives

| New (ours) | Purpose |
|---|---|
| `perception/encounter_sim/scene.py` | Staggered-arrival camera (extends `ScenarioCamera`), map walk-in paths, talkativeness |
| `perception/encounter_sim/dialogue.py` | Menu, selection guard, extraction guard (ported), simulated replies. No LLM import |
| `perception/encounter_sim/llm.py` | `FakeLLM`, `RecordingLLM`, `ReplayLLM`, `OllamaLLM` (urllib) |
| `perception/encounter_sim/run.py` | Drives the encounter, builds the handoff, runs his tour through the splice, returns encounter plus tour records |
| `perception/encounter_sim/recorded/s2_qwen2.5-7b.jsonl` | The recorded LLM outputs for the video |
| `perception/tests/test_encounter_sim.py` | Ids, clusters, schema, guards, D7/D2 structural checks, fake and replay determinism |

`sdc/` gets no change, and no LLM code goes anywhere near it.

| Joey's file | Needed? | Smallest change |
|---|---|---|
| `viz/replay_template.html` | **Yes**, for any UI change | Additive, as in D, about 80–120 lines. Forking it would be worse |
| `make_replay.py` | Only if the flag must live there | Four lines: `--encounter` → lazy-import `perception.encounter_sim.run` and prepend its records. Alternative: **no edit**, and our wrapper `python3 -m perception.encounter_sim.replay s2_multi_stop` calls his `build()` |
| `sdc/sim.py` | No | (If Joey dislikes the in-process splice: a `sim_cls=TourSim` parameter on `run_tour`, one line) |
| `sdc/profile.py` | Only for option C(b) | See C |
| `perception/tracker.py`, `perception/encounter.py` (ours) | Yes | `id_fmt` option; `_num` parses trailing digits |

## F. Check (if time allows; after the video)

Run s2_multi_stop (and s1_closed, which is cheap), 20 seeds, policy `ours`, under three conditions:
1. Our handoff **without** pending layers;
2. **With** the conversation's layers (fake LLM, so it can be rerun);
3. With one wrong layer per answering visitor (extraction error).

Report:
- steering uptake, misread rate and P13;
- for v4: the robot's non-routine actions toward v4 (`gaze_at visitor:v4` other than gaze balancing, additions driven by v4's layers) against condition 1, as a pressure proxy (H3).

Expected but **not verified**: v4 never answers, so it gets no layers and no pressure from this route. Any change would come from other visitors' layers changing which additions run.

## G. The video

- **Scenario:** `s2_multi_stop` with the encounter. Simulated time is −45 to 390 s. Proposed edit: about 2.5 minutes in total.
  - The encounter at 1× (45 s).
  - Stop 1 at 4×.
  - Stop 2 at 2× around the exclusion (t ≈ 150–175 s, the existing figure).
  - The choice and move at 4×.
  - Stop 3 at 8×.
- Recorded by screen capture of the replay page.

**What is simulated and what is real:**

| Simulated | Real code running |
|---|---|
| Visitors' movement, gaze and speech (Joey's sim rules plus our scripted arrival) | Our tracker, stable gate, companion clusters, engagement trigger |
| Camera input (face boxes, no pixels); the age estimator's outputs | The question menu, the selection and extraction guards, the handoff |
| Visitors' answers (templates over hidden interests) | The LLM's choices and extractions (`qwen2.5:7b`, recorded once, replayed) |
| The robot's body (the triangle is its commanded pose) | Joey's decision loop, profile store and measures |

**On-screen captions:**
1. (−45 s) "Simulation. Six visitors arrive. Our perception tracks each one and groups companions from how they move together."
2. (−34 s) "The group stops in front of the robot long enough: the encounter starts. The robot greets everyone at once."
3. (−27 s) "Two short questions to the whole group. An LLM picks the next question from a fixed menu and turns answers into small guesses; fixed rules check every guess. Nobody is asked by name, and quiet visitors are left alone."
4. (−3 s) "The robot's first impression: who is together, a child/adult estimate that is never spoken, and what people said they'd like."
5. (0 s) "The tour starts. Each guess is tested by the robot's offers and dropped if nobody responds."
6. (≈ 155 s) "The child is behind their parent and trying to join: the robot opens the formation for them."
7. (end) "Simulated visitors; real perception and decision code. No camera images or audio were used."

## H. Size

| Item | Hours: video by Nov 20 | Later |
|---|---|---|
| Encounter driver, scene, ids/guard, handoff, splice, records | 4 | |
| Dialogue: menu, guards, replies, fake/record/replay LLM | 4 | |
| Ollama client and the recording run (after your OK) | 1.5 | |
| Template changes (D) and the no-change check | 5 | |
| Wrapper or flag | 0.5 | |
| Tests (perception) plus the full test runs | 2 | |
| Screen capture, edit, captions | 2 | |
| **Subtotal** | **19** | |
| F check (3 conditions × 2 scenarios × 20 seeds) and a FINDINGS note | | 3 |
| Map positions projected into the camera scene (one geometry for both) | | 4 |
| Age in the profile store (C(b)), if wanted | | 2 |
| HANDOFF line (after merge approval) | | 0.2 |

19 hours by Nov 20 is tight. If time runs short, cut in this order:
1. LLM selection: fixed order, with the LLM doing extraction only (saves about 1 h);
2. the cluster-ring polish: colour only (about 1 h);
3. the "Visitors say" line: speech bubbles only.

## Decisions needed

| # | Question | Whose | My default |
|---|---|---|---|
| 1 | Edit `viz/replay_template.html` (additive) | Joey | Yes, as in D |
| 2 | The `--encounter` flag in `make_replay.py` (a 4-line edit of a root script; this deviates from the earlier "no edits to Joey's root scripts" rule) or our wrapper | Jay, Joey | Wrapper |
| 3 | Age: UI only (C(a)) or a profile field (C(b)) | Joey | C(a) |
| 4 | Talkativeness levels (invented; v4 never answers) | Jay | As in B |
| 5 | Show the simulated visitors' answer text in the replay. The kept log normally redacts speech (Q13); these visitors are fictional | Jay, Joey | Show it with the label "simulated", only in encounter-sim replays |
| 6 | Use local Ollama `qwen2.5:7b`; allow one recording run (about 15 local calls) | Jay | Yes |
| 7 | Show "child/adult" on the map in a public video, marked "internal estimate" | Joey (D4) | Yes, with the caption |
| 8 | A "short version" answer stores nothing (no vocabulary for less depth) | Joey | Yes |
| 9 | Video venue limits (length, captions, audio) | Jay | 2.5 min, captions, no audio |
| 10 | Ids by scripted arrival order plus a guard (A); fallback renames v2 | Jay | Arrival order |

## Deviations from the brief

- **Ids.** Ours are not his ids by default (v2 → visitor_6 in my run). The plan makes them equal by scripted arrival order plus a small `id_fmt` change in our tracker, with a runtime guard. It is not a mapping layer, but it is a constraint on the sim script.
- **The impression is taken at the handoff, not at the engagement event.** At the event, the clusters are split; 5 s later they were right in 20/20 seeds.
- **The `make_replay.py` flag** conflicts with the standing rule against editing his root scripts; I propose a wrapper unless you and Joey say otherwise.
- **`responded_to_steer_invite` and `age_conf`** are written as asked, but his loop never reads them.
- **The LLM's question selection** is a near-trivial choice with this menu and budget, and the fixed order is its fallback.
- **The answer text in the replay** needs an exception to Q13's redaction (decision 5).
- **Not run:** Joey's 99 tests and the perception tests. Nothing in the repo changed apart from this file.
