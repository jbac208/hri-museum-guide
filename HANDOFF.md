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
| D1 average without misery | Next-stop choice: maximise the weighted group score (no per-option exclusion filter, Joey 2026-11-12). The "no misery" floor is enforced within stops by the exclusion handler (P13) |
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
- 2026-11-11: Joey's answers. **Q1** outside the formation is a barrier even after leaving by choice (harmless without a bid; lets someone who wants back in count as excluded); s1 label added for v5. **Q2** robot-only blocked view is not a barrier; exhibit blocked is (`BARRIER_USE_LOS_ROBOT=False`). **Q3** a talked-over question is bid + barrier *and* point_ask: fix first, then answer (`OVERLAPPED_QUESTION_IS_POINT_ASK=True`). **Q4** an exclusion episode ends only when the barrier clears. **Q5** moving closer from outside the formation = bid (edging in), from inside = approach. Mock fixed so v2's short robot glances appear; glance cue now fires on its own at 65 s. s1: 100% precision/recall on all kinds.
- 2026-11-11: **Task 2 done.** `sdc/profile.py` + `tests/test_profile.py`. On s1: v1 pending carving + depth, v3 confirmed paint + figurehead, v2 confirmed figurehead (talked-over question), v5 pending ship_model, v4/v6 none. Provisional (Joey to confirm): **Q6** a rescinded layer isn't reopened by the same evidence within the stop, but an explicit point/ask does re-confirm it (`POINT_ASK_REOPENS_RESCINDED=True`) · **Q7** a question with no pointed feature confirms `exhibit_interest` on the current stop · confidence values (`LAYER_EVENT_CONF`, `SEED_LAYER_CONF`, `PENDING_WEIGHT`, `LAMBDA_DOMINANCE`) are placeholders.
- 2026-11-11: **Task 3 done.** `data/content/{figurehead,ship_model,compass}.json` + `sdc/content.py` (loader, validator incl. a D7 phrase lint, keyword Q&A) + `tests/test_content.py`. Core script with gaze/gesture cues per segment, open question, 4–6 additions tagged `type` (detail/depth/neighbour) and `serves` (`{kind, target}` layers, read by s_i(a)), canned Q&A answering all five s1 questions. Content is invented (fictional ship *Marigold*). Open: **Q8** addition lead-ins are neutral ("One more thing about the carving…") and never mention visitors' behaviour, which is stricter than D7's "A few of you seem curious…" example, since that phrasing would single out a lone lingerer.
- 2026-11-11: **Task 4 done.** `sdc/decision.py`, `sdc/loop.py`, `run_loop.py`, `tests/test_decision.py`. Open loop on s1: v2 excluded at 54 s → glance + turn, step back at 60 s, pause + gaze when talked over at 73 s, then her question is answered to the group; 2 additions (both taken up), all 5 questions answered, v3 ends with the highest credit (weight 0.29), no unresolved episodes, next stop = P12 two-way choice (no confirmed interest in either option). Open: **Q9** D1's next-stop filter ("an exhibit a child can't see") conflicts with D4 (child/adult only seeds baselines), and the gallery has no access data, so `would_exclude()` is a no-op hook · **Q10** credit k_i grows when a question is answered or an addition is taken up (not on delivery alone) · **Q11** questions are answered at the next speech gap in any phase, and answers don't count toward the P11 cap · **Q12** the next-stop planner counts confirmed layers only (per §6), so v5's pending drift doesn't steer it · open-loop artifacts until task 5: talked-over at 72 s comes from the mock's scripted robot speech; uptake is trivially true for someone already lingering.
- 2026-11-11: **Task 5 done.** `sdc/sim.py` (frames from the robot's commanded pose + speech; visitors react: hidden interests drive uptake, opening the formation lets v2 in, questions wait for a gap or interrupt), `scenarios.s1_closed`, `run_sim.py`, `tests/test_sim.py`; `mock.World` factored out (byte-identical output). On s1_closed: v2 excluded at 54 s, joins 2 s after the robot turns, resolved in 4 s (open loop: 30 s); interrupts at 77 s → pause, floor, answer; v2's depth guess rescinded (misread). Over 30 seeds: uptake 96% when the interest is real, 16% when it isn't; 0 unresolved episodes; v3 always lowest weight; without the join reaction the episode stays unresolved (P13 visible). Uptake changed: one continuous look ≥ max(`UPTAKE_LOOK_S`, `UPTAKE_DWELL_FACTOR`×own dwell) at a feature or another exhibit (not the stop as a whole), stepping closer measured once an earlier move has settled, or a question. Fixed: stream end was counted as resolving an episode. Sim parameters live in `sim.py`, not `config.py` (harness, not robot).
- 2026-11-11: **Task 6 done.** `sdc/metrics.py` + `tests/test_metrics.py`; `run_sim.py`/`run_loop.py` print the measures, `--log out.jsonl [--anon]` writes the event log (meta, track @ `LOG_TRACK_HZ`, event, profile, action, note, measures). Measures come from the log alone. Steering uptake = steering signals (linger/approach/drift/point_ask) answered or addressed by a later addition, ÷ detected. s1_closed over 30 seeds: steering uptake 0.64 (0.54–0.78), misread rate 0.40 (0–0.67), dominance share 0.57 (v3), time to resolve 2.3 s (1–4), P13 0. Fixed: back-to-back questions were merged into one point_ask. Open: **Q13** visitor speech text is redacted from the log (only the matched answer id stays); OK, or keep question text? **Next: task 8 (replay visualiser)** (task 7 scenarios can follow; minimum demo = 1, 2, 4, 5, 6, 8 on s1 + s2).
- 2026-11-11: **Task 8 done (single stop).** `make_replay.py` + `viz/replay_template.html` + `tests/test_replay.py` → `replay/<scenario>.html` (gitignored), self-contained, no network. Map zoomed to the group (other exhibits pinned to the corners with distances), robot commanded pose + gaze line, blocked-view dashes, formation band, excluded/barrier rings, signal badges; timeline of robot speech/actions (exclusion fixes in red) and per-visitor events, ✓/✗ uptake, sim reactions, reasons on hover, click to seek; profile layers + weights over time; measures. Space/arrows, `?t=72`, "Export map" → SVG for the paper figure. Preview: `.claude/launch.json` "replay" serves `replay/` on :8765. Needs multi-stop support once s2 exists. **Next: task 7, s2_multi_stop (needs multi-stop loop: transitions, falling behind, carrying baselines/credit across stops).**
- 2026-11-11: **s2_multi_stop done (task 7 part 1) → minimum demo complete (tasks 1, 2, 4, 5, 6, 8 on s1 + s2).** `sdc/tour.py` (one signal layer + profile store per tour; per-stop controllers; plan → optional P12 offer read from weighted orientation/gaze → move on at the planned pace → slow down for anyone falling behind → wait until everyone arrives), `SignalLayer.set_stop/set_transition` (falling behind = far from the robot and well behind the group median), `TourSim` + `scenarios.s2_multi_stop`, `run_tour.py`, multi-stop replay (`python3 make_replay.py s2_multi_stop`), `tests/test_tour.py`. Gallery: added a sea chest exhibit + route branches (mock data) so the second decision has two options. s2: figurehead → ship model (D1: v5's confirmed interest) → sea chest (P12 offer; v3's low weight loses) ; v2 excluded at stop 2, resolved in 3 s; v6 falls behind on move 2 → slow down + wait 8 s; seed weight 0 at stop 3; steering uptake 0.71, misread 0.2, P13 0, stable over 10 seeds. Open (Joey): **Q14** falling behind is handled without a bid (floor: slow down + wait), and is not counted as an exclusion episode · **Q15** "depth raised" = one depth addition joins the next stop's core (not counted toward P11); not triggered in s2 · **Q16** P12 reading = w_i-weighted seconds facing/looking at each option over `CHOICE_WAIT_S`; the offer is a statement ("Next we could see A or B."), no vote · **Q17** wait at most `WAIT_MAX_S` (45 s) for everyone, then start with a note · no tour-close behaviour (owner open). **Next: s3_dominant, s4_misread (task 7), then optional baselines (task 9).**
- 2026-11-12: **Q9 answered (Joey): no next-stop exclusion filter.** Not core to the concept, too nuanced; `would_exclude()` removed, the planner scores all route options. Joey to update §6.4 / D1 wording in the vault.
- 2026-11-12: **Q10 answered (Joey): credit when acted on.** k_i += 1 whenever the robot answers i's question or delivers an addition driven by i's layer, taken up or not (matches loop doc §1 and D3). Uptake now only confirms/rescinds. Effect: a misread still costs weight (s2: v6 gets 1 credit from a rescinded depth guess); s2 route and choices unchanged. The Implementation doc's example (credit on confirm) is now out of date — Joey to update.
- 2026-11-12: **Q11 answered (Joey).** Questions are answered at the end of the sentence being said (a pause ends at once), then the rest resumes; answers stay outside the P11 cap; a late question is still answered and the stop overruns. s1_closed: all 5 questions answered (was 4), waits 1–8 s (was up to ~15 s).
- 2026-11-12: **Q12 answered (Joey): next stop counts confirmed guesses only** (loop doc §6, design principle 3); close calls go to the P12 offer. No code change; test added.
- 2026-11-12: **Q13 answered (Joey): keep speech during the tour, delete at tour end.** The live log (`records()`) keeps question text; `Loop/Tour.end_tour()` returns the log to keep with visitor speech stripped (`metrics.redact_speech`), scrubs live event reasons, and discards per-visitor state. `--log` files and replays are written from that end-of-tour copy, so they show `"[speech]"`.
- 2026-11-12: **Q14 answered (Joey): falling behind is a floor rule with its own measure.** Always slow down + wait at the next stop, no bid needed (D4, §4, §6.2); reported as `falling_behind`, not as an exclusion episode. No code change. Vault: D10 still lists falling behind among barriers for the excluded test — Joey may want to note the exception.
- 2026-11-12: **Q15 answered (Joey): raised depth = one depth addition joins the next stop's core** (said to everyone, no P11 slot). Fixed: it was listed among the stop's additions; now `summary.core_depth`. Tests trigger it (not reached in s2: needs > half the group with confirmed depth).
- 2026-11-12: **Q16 answered (Joey): keep P12, weighted by w.** Two close options → "Next we could see A or B." (a statement, no vote) → read w_i-weighted seconds facing/looking at each option over `CHOICE_WAIT_S`; no reaction → planner default. No code change. Joey to mark P12 agreed in the vault.
- 2026-11-12: **Q17 answered (Joey): cap the wait and count it.** Wait up to `WAIT_MAX_S` (tunable, 45 s), then start; late arrivals go through the normal exclusion handler; `measures.falling_behind.stops_started_without_everyone` / `missing` record it as a floor miss (s2: 0). **All open design questions Q1–Q17 answered.** Remaining open: tour-close owner, interface v0.1 sign-off (Joey/Jay). Vault to update (Joey): §6.4/D1 (Q9), Implementation credit example (Q10), D10 falling-behind note (Q14), P12 agreed (Q16). **Next: task 9 (baseline comparison), then optional s3/s4.**
- 2026-11-12: **Task 9 done.** `sdc/policies.py` (ours · one_size, Burgard 1999 · engagement, Lin 2024 — switches over the same decision layer), `compare_policies.py` → `results/policies.md` (gitignored), `tests/test_policies.py`. Results (simulated visitors, mean over 20 s1 / 10 s2 seeds): P13 unresolved 0 (ours) vs 0.17 (both baselines: the child stays excluded); steering uptake s1 0.72 / 0.62 / 0.69, s2 0.71 / 0.48 / 0.71; dominance share s1 0.57 / 0.80 / 0.62, s2 0.41 / 0.83 / 0.45; time to resolve 2.4 s vs never (position barrier); baselines start stops without the slow walker. Misread rate mixed (ours 0.39 vs engagement 0.17 in s1, 0.23 vs 0.43 in s2). Caveat for the paper: sim rules (e.g. the child only joins when invited) drive the exclusion result; this demonstrates mechanisms, not real-visitor effects. **Next (optional): s3_dominant, s4_misread; paper figures.**
- Open (Joey/Jay): interface v0.1 sign-off · whether perception or block 3 computes `attention` / `los_*` / `in_formation` · whether `posture` is feasible · who owns ASR · start-impression contents (P16) · who owns the tour close.
