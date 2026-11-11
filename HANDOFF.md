# Handoff: HRI 2027 SDC museum guide robot (processing loop)

You're taking over the **software prototype** for Joey's half of a team entry to the HRI 2027 Student Design Competition. Read this file, then the design docs linked below, before writing code.

- **Deadline:** submission **Nov 20, 2026, 23:59 AoE** (≤4 pages incl. refs, not anonymous, video optional). Notification Dec 18 · camera-ready Jan 2, 2027.
- **Target:** a demo-able closed loop by **~Nov 16**, leaving 4 days for the paper.
- **Call for papers:** https://humanrobotinteraction.org/2027/?p=369. Software-only entries are explicitly fine.

## 1. The project in one paragraph

An *inclusive* museum guide robot for one-off tour groups (visitors are never seen again, so nothing persists past the tour). It guarantees every visitor a floor of *opportunity* to take part, then picks what's best for the group on average ("average without misery"). Visitors steer the tour through natural behaviour (lingering, approaching, asking, drifting). The robot builds each visitor's impression in small, reversible **profile layers**. It tests each one with a small **addition** to the shared content and confirms or rescinds it depending on **uptake**. It intervenes only for visitors who are **excluded** (a bid to take part *and* a barrier), never for those who are just **reserved** (quiet but content).

## 2. Who owns what

| Block | Owner | Status |
|---|---|---|
| 1–2: initial encounter, sensors, perception (tracking, orientation, line of sight, clusters, child/adult) | **Jay** | Not started on Jay's side; **we mock it** |
| 3–8: signal layer → profile store → decision layer → content → behaviour → logging | **Joey (this repo)** | Interface + mock data done; everything else to build |

**There's no robot hardware.** Behaviour is a stream of abstract action commands that get logged and visualised.

## 3. Source-of-truth docs (Joey's Obsidian vault)

The design lives in Obsidian, not in this repo. The vault folder on Joey's Mac is:

`/Users/joeyback/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault/HRI SDC/`

| Doc | Read it for | Obsidian link |
|---|---|---|
| `Design decisions.md` | **Agreed rules D1–D10** + proposals P11–P16, scope, team split. Highest authority. | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FDesign%20decisions) |
| `Perception & decision loop.md` | Joey's half in detail: signal vocabulary (§2), the within-stop loop (§3), exclusion fixes (§4), the addition scoring formula (§5), between stops (§6), the four live measures (§7) | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FPerception%20%26%20decision%20loop) |
| `Implementation (perception & decision loop).md` | The architecture chart (blocks 1–8), component list, tunable parameters, build path | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FImplementation%20%28perception%20%26%20decision%20loop%29) |
| `Interface (perception → processing).md` | Data contract v0.1 (block 2 → 3), with open questions for Jay | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FInterface%20%28perception%20%E2%86%92%20processing%29) |
| `updating notes.md` | Status / timeline | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2Fupdating%20notes) |
| `Related works.md` | Citations behind the decisions (Masthoff 2004, Gillet 2021, Kuzuoka 2010, Claure 2026, …) | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FRelated%20works) |

**Rules for the vault:** read freely. **Don't edit design docs.** If the implementation forces a design choice that isn't covered, stop and ask Joey, or note it in §8 below as a proposed P-number. Joey records every design decision in `Design decisions.md` himself.

## 4. Design rules the code must respect

| Rule | What it means in code |
|---|---|
| D1 average without misery | Next-stop / option choice: first filter out options that leave anyone excluded, then maximise the weighted group score |
| D2 + D10 floor / excluded test | `excluded = bid AND barrier` (same visitor, overlapping in time). Bid alone = steering. No bid + calm attention = reserved → **no action, ever** |
| D3 success measure | Steering uptake = share of detected steering signals the robot visibly acts on, per stop. **Not** engagement |
| D4 cues | Behaviour only. **Never** add gender/ethnicity/appearance features. Child/adult (height) is the only class, and it only seeds baselines. Judge every signal as a *deviation from that visitor's own baseline* (seeded by the start impression, running average, seed weight fades to 0 by stop 3) |
| D5 timing | Gaze balancing from t=0. Content changes (additions) only after behavioural evidence |
| D6 misreads | No uptake within the window → rescind the layer, never repeat that addition |
| D7 acknowledgement | All speech goes **to the group**, never names or describes one visitor. Acknowledge nonverbally first (gaze/turn/nod) |
| D8 dominance | `w_i = 1 / (1 + λ·k_i)`, where `k_i` = that visitor's steering credit |
| D9 bystanders | Ignore non-tour people |
| P11 (proposed) | ≤ 2 additions per stop |
| P13 (proposed) | "Misery" = an exclusion episode still unresolved at the end of a stop |
| Additive | Additions never remove core content |
| Privacy | No video. Only tracks + events. All per-visitor state is discarded at tour end |

Addition score (§5 of the loop doc): `score(a) = Σ_i w_i · s_i(a)`. Confirmed layers count fully toward `s_i`; pending layers count partly. Companions: an addition triggered by one cluster member is delivered facing the whole cluster.

Fixes by barrier (§4): view blocked / outside formation → rotate or step to open the formation · talked over → pause + gaze to them · falling behind → slow down / wait. Never a direct question.

All thresholds (λ, uptake window ≈10 s, addition threshold, baseline window, per-event deviation thresholds) are **named tunables in one config module**. The paper will call them tunable, not give numbers.

## 5. What exists now

```
sdc/schema.py      interface v0.1 as an executable validator (validate_line / validate_stream)
sdc/mock.py        mock perception generator: scripted behaviour → schema stream; derives line of sight,
                   formation, overlapped speech and head yaw geometrically so fields stay consistent
sdc/scenarios.py   scripted scenarios + ground-truth labels (currently: s1_one_stop)
make_mock.py       regenerates data/<scenario>.jsonl + .labels.json
data/gallery.json  mock gallery: figurehead (stop), ship_model, compass; route branches
tests/test_mock.py 9 checks (schema validity + derived fields match the script)
```

Run (pure Python 3.10+, no dependencies):

```
python3 make_mock.py
python3 tests/test_mock.py     # or: python3 -m pytest tests
```

**Scenario `s1_one_stop`** (150 s, one stop, 6 visitors; robot speaks core 10–90 s, open question 95–99 s):

| Visitor | Behaviour | Expected events (see labels file) |
|---|---|---|
| v1 adult | Steps closer and fixes on the carving, 70–115 s | approach 70–80, linger 70–115 |
| v2 child | Behind parent v3 (view blocked, outside formation) until ~84 s; edges in + short robot glances 50–80; talked over by the robot at 72 s | barrier 0–84, bid 50–80, **excluded 50–80** |
| v3 adult | v2's parent; points + asks 4 questions | point_ask ×4 → dominance test |
| v4 adult | Quiet, calm, attending | **expect_no_events** (reserved) |
| v5 adult | Drifts toward the ship model, 100–140 | drift → ship_model |
| v6 adult | v5's companion; leans, faces away, 110–150 | fatigue |

**Mock is open-loop:** visitors don't react to the robot. Closed-loop reactions are task 5 below.

**Interface status:** v0.1 is a **draft, not yet agreed with Jay** (questions at the bottom of the interface doc). Keep all block-3 code reading the stream through one adapter, so field changes stay cheap.

## 6. Tasks, in order

Each one should end with tests passing and a one-line entry in §8.

1. **Signal layer** `sdc/signals.py`: per-visitor features at ~1 Hz (dwell per attention target, distance to exhibit/robot, robot-glance rate, speech onsets) → baseline → deviation → rule-based events: `linger, approach, point_ask, drift, fatigue, bid, barrier`, plus derived `excluded`. Add `eval_signals.py`, which scores detected events against `*.labels.json` (per-kind precision/recall with time tolerance, and detection latency).
   **Accept on s1:** v2 `excluded` detected within the 50–80 window with ≤5 s latency · **zero events for v4** · v1 linger/approach, v3 point_ask ×4, v5 drift and v6 fatigue all detected · no `excluded` for anyone else.
2. **Profile store** `sdc/profile.py`: profile layers per visitor (`feature/kind`, `pending|confirmed|rescinded`, confidence) + steering credit `k_i`. Created by events (linger/approach/drift → pending; point_ask → confirmed). Deleted at tour end.
3. **Content** `data/content/*.json`: hand-written core script + 4–6 additions per exhibit, tagged by feature and type (detail / depth / neighbouring exhibit). Keep it short and plausible; no live LLM.
4. **Decision layer** `sdc/decision.py`:
   - stop controller (state machine: arrange → core → open space → sense/respond/check, looping while time remains);
   - exclusion handler (top priority, fix by barrier type);
   - addition selector (score formula, threshold, ≤2 per stop, never repeat a rescinded one);
   - uptake monitor (~10 s window over the addressed visitors → confirm/rescind + credit);
   - between-stop planner (pace, depth, next stop by D1).

   Output: abstract actions (`say_to_group(text)`, `gaze_at(target)`, `turn_body(yaw)`, `step_to(x,y)`, `pause(s)`, `slow_down()`), each logged with the reason that triggered it.
5. **Closed-loop visitor sim** `sdc/sim.py`: visitors with hidden interests react to the robot's actions (uptake probability depends on whether an addition matches a hidden interest; a barrier clears when the robot opens the formation; and so on). Needed to show confirm/rescind, misreads and dominance damping.
6. **Logging + measures** `sdc/metrics.py`: event log (tracks + events, no video), plus the 4 live measures (steering uptake, exclusion episodes + time-to-resolve, misread rate, dominance share), plus the P13 headline (share of visitors with an unresolved episode, which should be 0).
7. **More scenarios:** `s2_multi_stop` (3 stops: baseline learning, between-stop choice, P12 two-way choice), `s3_dominant` (one visitor steers constantly, so weight damping is visible), `s4_misread` (an addition gets no uptake → rescind, no repeat).
8. **Replay visualiser** (single self-contained HTML, top-down): visitors, robot, line-of-sight/exclusion highlighting, a timeline of events and actions with reasons. This is the demo, and the source for a paper figure.
9. **Optional baseline comparison:** run the same sim with a one-size-fits-all policy and an engagement-maximising policy, and report the 4 measures. Good for the paper's evaluation paragraph (P14).

If time runs short, the minimum demo is tasks 1, 2, 4, 5, 6 and 8 on s1 + s2.

## 7. Conventions

- Python 3.10+, standard library only for `sdc/` (matplotlib OK in viz/scripts only). Tests in `tests/` must run with plain `python3 tests/<file>.py` and with pytest.
- Rules over learned models: there's no training data, and every decision must be explainable in the paper. Every action carries a human-readable `reason`.
- Deterministic: seeded RNG everywhere.
- Generated files (`data/*.jsonl`, `data/*.labels.json`) are gitignored. Regenerate with `make_mock.py`.
- Joey prefers succinct communication. Commit in small steps with clear messages. Don't push without asking.

## 8. Status log / open items

- 2026-11-11: Repo created; interface v0.1, mock generator, s1 scenario and tests moved in from the vault. **Next: task 1.**
- 2026-11-11: **Task 1 done.** `sdc/config.py` (tunables), `sdc/adapter.py` (single stream reader), `sdc/signals.py`, `eval_signals.py`, `tests/test_signals.py`. s1: all labels found, v2 excluded at 54 s (4 s latency), v4 zero events; also holds on 40 other mock seeds. Only FP: v5 `barrier` 142–150 (see Q1). **Awaiting Joey's answers to Q1–Q5 before task 2.**
- Open (Joey), provisional defaults in `config.py`: **Q1** is standing outside the formation a barrier even after leaving it by choice (v5 after the drift)? · **Q2** should a blocked view of the *robot* alone be a barrier (`BARRIER_USE_LOS_ROBOT=False`; if True, v3/v4 get barriers when v1 steps in) · **Q3** a question that was talked over = bid + barrier, not point_ask (`OVERLAPPED_QUESTION_IS_POINT_ASK=False`) · **Q4** an exclusion episode ends only when the barrier clears, not when the bid stops · **Q5** edging in vs approach split by formation: moving closer from outside = bid, from inside = approach.
- Open (Joey/Jay): interface v0.1 sign-off · whether perception or block 3 computes `attention` / `los_*` / `in_formation` · whether `posture` is feasible · who owns ASR · start-impression contents (P16) · who owns the tour close.
