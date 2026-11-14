# Handoff: HRI 2027 SDC museum guide robot

**Next job: outline the paper.** The software prototype for Joey's half (the processing loop) is built, tested and pushed. This file briefs the next agent: what the system is, what was built, what was decided along the way, what the results are and what's still open. Read it top to bottom, then the vault docs in §3.

- **Deadline:** submission **Nov 20, 2026, 23:59 AoE**. ≤ 4 pages including references, not anonymous, video optional. Notification Dec 18 · camera-ready Jan 2, 2027. Theme: *Robots in Public Spaces*.
- **Call for papers:** https://humanrobotinteraction.org/2027/?p=369. Software-only entries are explicitly fine.
- **Team:** Joey (perception & decision loop, this repo) and Jay (initial encounter + perception). The paper is written together; Jay's half isn't in this repo, so ask Joey for its status.
- **Rules for agents:** don't edit the design docs in the vault (Joey records decisions there). Ask Joey before deciding anything the docs don't cover. Keep replies to Joey succinct. Don't push without asking. Ask Joey **where the outline should live** (a new vault note, a doc, or this repo) before writing it.

## 0. Status at a glance (2026-11-14)

| Task | Status |
|---|---|
| 1 Signal layer + eval | Done. s1: 100% precision/recall on all event kinds; v2 excluded at 54 s (4 s latency); reserved v4 zero events |
| 2 Profile store | Done |
| 3 Content (4 exhibits) | Done (invented ship *Marigold*) |
| 4 Decision layer | Done |
| 5 Closed-loop visitor sim | Done |
| 6 Event log + live measures | Done |
| 7 Scenarios | `s2_multi_stop` done. `s3_dominant`, `s4_misread` **not built (optional; Joey: not now)**. Dominance damping and misreads already show in s1/s2 |
| 8 Replay visualiser | Done (single and multi-stop) |
| 9 Baseline comparison | Done (results in §7) |

99 tests pass (`python3 run_tests.py`). All design questions Q1–Q17 are answered by Joey (§8).

## 1. The project in one paragraph

An *inclusive* museum guide robot for one-off tour groups (visitors are never seen again, so nothing persists past the tour). It guarantees every visitor a floor of *opportunity* to take part, then picks what's best for the group on average ("average without misery"). Visitors steer the tour through natural behaviour (lingering, approaching, asking, drifting). The robot builds each visitor's impression in small, reversible **profile layers**. It tests each one with a small **addition** to the shared content and confirms or rescinds it depending on **uptake**. It intervenes only for visitors who are **excluded** (a bid to take part *and* a barrier), never for those who are just **reserved** (quiet but content).

## 2. Who owns what

| Block | Owner | Status |
|---|---|---|
| 1–2: initial encounter, sensors, perception (tracking, orientation, line of sight, clusters, child/adult) | **Jay** | Mocked here (`sdc/mock.py`, `sdc/sim.py`). Interface v0.1 not yet signed off with Jay |
| 3–8: signal layer → profile store → decision layer → content → behaviour → logging | **Joey (this repo)** | Built |

There's no robot hardware. Behaviour is a stream of abstract actions (`say_to_group`, `gaze_at`, `turn_body`, `step_to`, `pause`, `slow_down`), each logged with the rule that triggered it, and replayed in a browser.

## 3. Source-of-truth docs (Joey's Obsidian vault, read-only)

Folder: `/Users/joeyback/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault/HRI SDC/`

| Doc | Read it for | Obsidian link |
|---|---|---|
| `Design decisions.md` | Agreed rules **D1–D10**, proposals P11–P16, scope, team split. Highest authority | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FDesign%20decisions) |
| `Perception & decision loop.md` | Joey's half: signal vocabulary (§2), within-stop loop (§3), exclusion fixes (§4), addition score (§5), between stops (§6), live measures (§7), P11–P16. **Ends with a ≈380-word draft of the system-design section** | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FPerception%20%26%20decision%20loop) |
| `Implementation (perception & decision loop).md` | Architecture chart (blocks 1–8), components, tunables, build path (WoZ → automate). **Ends with a ≈120-word draft feasibility paragraph** | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FImplementation%20%28perception%20%26%20decision%20loop%29) |
| `Interface (perception → processing).md` | Data contract v0.1 (block 2 → 3) and open questions for Jay | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FInterface%20%28perception%20%E2%86%92%20processing%29) |
| `updating notes.md` | Concept, five design principles, status/timeline | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2Fupdating%20notes) |
| `Related works.md` | Citations behind the decisions (Masthoff 2004, Gillet 2021, Kuzuoka 2010, Claure 2026, …) | [open](obsidian://open?vault=Obsidian%20Vault&file=HRI%20SDC%2FRelated%20works) |

**The vault drafts predate some implementation decisions.** Out of date as of now (Joey to update the vault; the paper should follow the implementation):
- Loop doc §6.4, the D1 wording and the draft paper text still say the next-stop choice first "removes options that would exclude anyone". That filter was dropped (Q9).
- The Implementation doc's walkthrough raises steering credit on confirmation; it now rises when the robot acts on a signal (Q10).
- D10 lists "falling behind" among barriers for the excluded test; falling behind is handled as a floor rule without a bid (Q14).
- P12 (two-way choice) is still marked *proposed*; Joey agreed to keep it (Q16). P11 and P13 are implemented as proposed.

## 4. Design rules → what the code does

| Rule | Implementation |
|---|---|
| D1 average without misery | Next stop = the route option with the best `Σ w_i·s_i` over **confirmed** layers (Q12); no per-option exclusion filter (Q9). The "no misery" floor is enforced within stops by the exclusion handler and checked by P13 |
| D2 + D10 floor / excluded test | `excluded = bid AND barrier` at the same time. Bid alone = steering. No bid + calm attention = reserved → nothing beyond routine gaze balancing |
| D3 success measure | Steering uptake = steering signals (linger, approach, drift, point/ask) the robot visibly acted on (answered, or addressed by an addition delivered after them) ÷ detected. Not engagement |
| D4 cues | Behaviour only; child/adult only seeds baselines. Every signal is a deviation from the visitor's own baseline; the start-impression seed counts like `SEED_WEIGHT_S` seconds at stop 1, half at stop 2, zero from stop 3 |
| D5 timing | Gaze balancing from t = 0 (least-looked-at visitor every `GAZE_SHIFT_S`); additions only in the respond phase, after evidence |
| D6 misreads | No uptake within `UPTAKE_WINDOW_S` → rescind the tested layer; an addition is never repeated |
| D7 acknowledgement | Glance at the visitor before an addition or answer; all speech is `say_to_group`; content is linted for singling-out phrases |
| D8 dominance | `w_i = 1/(1+λ·k_i)`; `k_i` += 1 when the robot answers i's question or delivers an addition driven by i's layer, landed or not (Q10) |
| D9 bystanders | Only tracked tour members are considered (mock has no bystanders) |
| P11 | ≤ 2 additions per stop; answers and a raised-depth core piece don't count (Q11, Q15) |
| P12 | Close next-stop scores → "Next we could see A or B." (a statement, not a vote), then w-weighted seconds facing/looking at each option over `CHOICE_WAIT_S` (Q16) |
| P13 | Headline = share of visitors with an exclusion episode unresolved at a stop's end |
| Additive | Additions never remove core content; a raised depth adds one depth piece to the next stop's core (Q15) |
| Privacy | Tracks + events only, no video. Visitor speech is kept during the tour and stripped at tour end; `end_tour()` discards all per-visitor state (Q13) |

## 5. What's built

```
sdc/schema.py       interface v0.1 as an executable validator
sdc/adapter.py      the one place block 3 reads the stream (field changes stay local)
sdc/config.py       ALL tunables, named and commented (the paper calls them tunable, no numbers)
sdc/signals.py      block 3: features → own baseline → deviation → events (linger, approach, point_ask,
                    drift, fatigue, bid, barrier, excluded); stop switching; falling behind on moves
sdc/profile.py      block 4: profile layers (pending/confirmed/rescinded, confidence) + steering credit, D8 weight
data/content/*.json block 6: per exhibit (figurehead, ship_model, compass, sea_chest): core script with gaze cues,
sdc/content.py        open question, 4–6 additions tagged by type + layers served, canned Q&A; D7 lint
sdc/decision.py     block 5: stop controller, exclusion handler, Q&A, gaze balancing, addition selector,
                    uptake monitor, between-stop planner
sdc/tour.py         multi-stop orchestration: plan → P12 offer → move on → slow for stragglers → wait
sdc/loop.py         single-stop wiring (signals → profile → decision)
sdc/metrics.py      block 8: event log (tracks + events), the live measures, speech redaction, anonymisation
sdc/policies.py     ours / one_size / engagement switches for the baseline comparison
sdc/mock.py         open-loop mock perception (scripted visitors); World builds schema frames
sdc/sim.py          closed-loop visitor sim: Sim (one stop) and TourSim (multi-stop); hidden interests
sdc/scenarios.py    s1_one_stop (open loop, labelled), s1_closed, s2_multi_stop
viz/replay_template.html + make_replay.py   self-contained replay page (the demo)
```

Commands (Python 3.10+, no dependencies):

```
python3 run_tests.py                 # regenerate mocks + run all 99 tests
python3 eval_signals.py -v           # signal layer vs ground-truth labels (s1)
python3 run_loop.py                  # open loop on s1, action log + measures
python3 run_sim.py                   # closed loop, one stop (s1_closed)
python3 run_tour.py                  # closed loop, three stops (s2_multi_stop)
python3 compare_policies.py          # baseline comparison → results/policies.md (~16 s)
python3 make_replay.py s2_multi_stop # replay → replay/s2_multi_stop.html (also s1_closed, s1_one_stop)
```

`--log out.jsonl [--anon]` on the run scripts writes the end-of-tour event log. Generated files (`data/*.jsonl`, `replay/`, `results/`) are gitignored. To view a replay in the Claude desktop app's browser pane, start the "replay" entry in `.claude/launch.json` (serves `replay/` on localhost:8765). In the replay, "Export map" saves the map at the current moment as SVG (candidate paper figure).

### Scenarios

- **s1_one_stop** (open loop, ground-truth labels): one 150 s stop, six visitors. v1 lingers on the carving and steps closer; v2 (child) is behind their parent, edges in, glances at the robot and is talked over → excluded; v3 (parent) points and asks four questions; v4 is reserved (must get zero events); v5 drifts toward the ship model; v6 leans and faces away (fatigue).
- **s1_closed**: the same people, but they react to the robot (v2 joins only when the robot opens the formation; questions wait for a gap or interrupt; hidden interests decide uptake).
- **s2_multi_stop** (closed loop): figurehead → ship model (D1: v5's confirmed interest) → sea chest (P12 offer; v3's low weight loses). v2 is excluded at stop 2 and resolved in ~3 s; v6 falls behind on the second move → the robot slows down and waits ~8 s; the seed no longer counts at stop 3.

## 6. How the system works (material for the system section)

**Signal layer (~1 Hz, per visitor, vs own baseline).** Baselines are running means seeded by the start impression and frozen while the related event is active, so an event doesn't become the new normal.
- *Linger*: one continuous look at a feature ≥ max(`LINGER_MIN_S`, `LINGER_FACTOR` × own mean dwell).
- *Approach*: closer to the exhibit than own in-formation baseline by `APPROACH_MIN_DROP_M`, inside the formation.
- *Point/ask*: pointing, or a question; a talked-over question also counts (Q3).
- *Drift*: gaze resting on another exhibit (unusual for this visitor).
- *Fatigue*: leaning/sitting, or facing away + looking at nothing + still.
- *Bid*: edging in from outside the formation, repeated short robot glances above own rate, or speech that was talked over.
- *Barrier* (absolute, not vs baseline): "position" = facing the stop with the exhibit view blocked or outside the formation (a robot-only blocked view isn't one, Q2); "talked over"; "behind" on moves.
- *Excluded*: bid AND barrier; the episode lasts until no barrier is left (Q4).

**Within a stop.** Arrange (face the group) → core (same for all; gaze cues on key words) → open space (pause, one open question to the group, wait) → respond loop. Always on: exclusion fixes (position → soft glance + turn to open the formation, step back once if still excluded; talked over → stop, hold the floor, gaze to them), answering questions at the end of the current sentence (Q11), gaze balancing. In the respond loop: best addition by `score(a) = Σ_i w_i·s_i(a)` above `ADDITION_THRESHOLD` (pending layers count `PENDING_WEIGHT`×confidence), delivered facing the companion cluster; uptake = a look at its target clearly longer than own dwell, stepping closer (after any earlier move settles), or a question.

**Between stops.** Remove rescinded layers → pace (slower if ≥ `PACE_FATIGUE_SHARE` fatigued or someone fell behind/stayed excluded) → depth (raised if > half have a confirmed depth layer) → next stop (D1, or P12 offer) → walk at the slowest visitor's pace; slow down for anyone falling behind; wait up to `WAIT_MAX_S` at the next stop (starting without someone is counted as a floor miss, Q17).

**Every action carries a human-readable reason** naming the rule and tunable, e.g. `excluded (position barrier): turn to open the formation toward them (Kuzuoka 2010, §4)`.

**Tunables** (all in `sdc/config.py`, ~80 names), grouped: signal timing and baselines (tick, debounce, seed weight/fade, baseline minimum, dwell prior) · per-event thresholds (linger, approach, point/ask, drift, fatigue, bid glance/edging, barrier on/off, behind) · profile (event→layer map, confidences, pending weight, λ) · stop controller timing (arrange, open-space wait, gaze shift, acknowledgement, pause for the floor, recheck, step back) · additions (threshold, cap) · uptake (window, look length, dwell factor, step) · planner (fatigue share, depth share, closeness for P12, choice reading) · moves (walk speeds, arrival radius, max wait).

## 7. Results (simulated visitors)

**Signal layer vs labels (s1, open loop, ±5 s):** every event kind at 100% precision and recall; detection latency: excluded 4 s, bid 4 s, barrier ~2 s, point/ask ~2 s, drift 3 s, fatigue 5 s, approach 5 s, linger 20 s (deliberately conservative). Holds on 40 other mock seeds.

**Baseline comparison** (`compare_policies.py`; same sims and seeds; mean [min–max]). Policies: **ours** · **one_size** (fixed tour, Burgard 1999: same script and additions for everyone, no exclusion fixes, fixed route, no waiting) · **engagement** (engagement-maximising, Lin 2024: serves whoever signals most, no dominance damping, pending guesses count fully, up to 4 additions, no exclusion fixes, no waiting). All three answer every question.

s1_closed (one stop, 20 seeds):

| measure | ours | one_size | engagement |
|---|---|---|---|
| steering uptake | 0.72 [0.58–0.88] | 0.62 | 0.69 [0.60–0.86] |
| exclusion episodes / resolved | 2 / 2 | 1 / 0 | 1 / 0 |
| time to resolve (s) | 2.38 [2.00–2.50] | – | – |
| P13 unresolved share | **0.00** | 0.17 | 0.17 |
| misread rate | 0.39 [0.00–0.67] | – | 0.17 [0.00–0.67] |
| dominance share | 0.57 [0.38–0.71] | 0.80 | 0.62 [0.50–0.71] |

s2_multi_stop (three stops, 10 seeds):

| measure | ours | one_size | engagement |
|---|---|---|---|
| steering uptake | 0.71 [0.71–0.72] | 0.48 [0.43–0.55] | 0.71 [0.65–0.79] |
| exclusion episodes / resolved | 2 / 2 | 2 / 1 | 2 / 1 |
| time to resolve (s) | 2.35 [2.00–3.00] | 7.20 [6–8] | 7.20 [6–8] |
| P13 unresolved share | **0.00** | 0.17 | 0.17 |
| misread rate | 0.23 [0.00–0.40] | – | 0.43 [0.00–0.60] |
| dominance share | 0.41 [0.39–0.42] | 0.83 | 0.45 [0.42–0.46] |
| fell behind / stops started without everyone | 1 / 0 | 1 / 1 | 1 / 1 |

Reading it: only our loop resolves the child's exclusion (the baselines' one "resolved" episode in s2 is the talked-over moment ending by itself; the position barrier never clears). The fixed tour lets one visitor take ~80% of the robot's responses; D8 damping beats the engagement robot only modestly. Steering uptake doesn't separate ours from engagement. Misread rate is noisy (1–3 tested guesses per stop) — report it, don't lean on it.

**Caveats the paper must state:** visitors are simulated by rules (e.g. the child only joins when the robot opens the formation; uptake probability depends on hidden interests), so these numbers illustrate the mechanisms, not real-visitor effects. Perception is mocked with small noise (3 cm), so thresholds were hand-set on scripted scenarios; real tracking needs re-tuning. The natural framing is: prototype + simulated walkthrough now, the WoZ field study in P14 as future work.

## 8. Implementation decisions beyond the design docs

Answered by Joey (each logged in the status log, §11, with details):

| # | Decision |
|---|---|
| Q1 | Outside the formation is a barrier even after leaving by choice (harmless without a bid) |
| Q2 | A blocked view of only the robot is not a barrier; a blocked exhibit view is |
| Q3 | A talked-over question is bid + barrier (fix first) **and** point/ask (then answer) |
| Q4 | An exclusion episode ends only when the barrier clears |
| Q5 | Moving closer from outside the formation = bid (edging in); from inside = approach |
| Q6 | A rescinded guess isn't revived by more of the same behaviour that stop, but an explicit question re-confirms it |
| Q7 | A question that names or points at nothing confirms interest in the current exhibit as a whole |
| Q8 | Addition lead-ins stay neutral ("One more thing about the carving…"), never about what visitors did — stricter than D7's example, so a lone lingerer isn't pointed at |
| Q9 | No next-stop exclusion filter (not core, too nuanced) |
| Q10 | Steering credit rises when the robot acts on a signal, landed or not |
| Q11 | Answer at the end of the current sentence; answers outside P11; late questions answered (stop overruns) |
| Q12 | Next stop counts confirmed guesses only |
| Q13 | Visitor speech kept during the tour, stripped at tour end |
| Q14 | Falling behind = floor rule (slow down + wait, no bid needed), own measure, not an exclusion episode |
| Q15 | Raised depth = one depth piece joins the next stop's core |
| Q16 | Keep P12; read the group's turning weighted by w |
| Q17 | Wait up to `WAIT_MAX_S`, then start; count it as a floor miss |

**Still open (Joey/Jay):** who owns the tour close (no closing behaviour is built) · interface v0.1 sign-off (who computes `attention`/`los_*`/`in_formation`, whether `posture` is feasible, who owns ASR, start-impression contents P16).

## 9. For the paper outline (next agent)

Inputs to draw on: §1 (concept), §4 (rules → implementation), §6 (system), §7 (results + caveats), §8 (decisions), the two vault drafts (system design ≈380 words, feasibility ≈120 words; update them per §3), `Related works.md`, P14 (future WoZ study: three conditions, measures, hypotheses H1–H3).

Candidate figures and tables (not made yet; Joey said not now):
- the architecture chart (blocks 1–8) from the Implementation doc;
- a replay map at a key moment, e.g. s2 at ~160 s (child excluded behind the parent, robot turned toward them) — `make_replay.py s2_multi_stop`, open with `?t=160`, "Export map";
- the replay timeline as an annotated strip (excluded → fix → resolved; question → answer);
- the baseline table from §7 (likely condensed to P13, steering uptake, dominance share).

Points to check with Joey before outlining: where the outline lives; how much space Jay's half (initial encounter) gets; whether the paper presents the simulated comparison or only the walkthrough; page budget per section within 4 pages including references.

## 10. Conventions

- Python 3.10+, standard library only in `sdc/` (matplotlib OK in viz/scripts only). Tests run with `python3 tests/<file>.py`, `python3 run_tests.py` or pytest.
- Rules over learned models; every action carries a `reason`. Deterministic, seeded RNG everywhere.
- Commit in small steps with clear messages; add a line to the status log below after each task. Don't push without asking.

## 11. Status log


- 2026-11-11: Repo created; interface v0.1, mock generator, s1 scenario and tests moved in from the vault. **Next: task 1.**
- 2026-11-11: **Task 1 done.** `sdc/config.py` (tunables), `sdc/adapter.py` (single stream reader), `sdc/signals.py`, `eval_signals.py`, `tests/test_signals.py`. s1: all labels found, v2 excluded at 54 s (4 s latency), v4 zero events; also holds on 40 other mock seeds. Only FP: v5 `barrier` 142–150 (see Q1). **Awaiting Joey's answers to Q1–Q5 before task 2.**
- 2026-11-11: Joey's answers. **Q1** outside the formation is a barrier even after leaving by choice (harmless without a bid; lets someone who wants back in count as excluded); s1 label added for v5. **Q2** robot-only blocked view is not a barrier; exhibit blocked is (`BARRIER_USE_LOS_ROBOT=False`). **Q3** a talked-over question is bid + barrier *and* point_ask: fix first, then answer (`OVERLAPPED_QUESTION_IS_POINT_ASK=True`). **Q4** an exclusion episode ends only when the barrier clears. **Q5** moving closer from outside the formation = bid (edging in), from inside = approach. Mock fixed so v2's short robot glances appear; glance cue now fires on its own at 65 s. s1: 100% precision/recall on all kinds.
- 2026-11-11: **Task 2 done.** `sdc/profile.py` + `tests/test_profile.py`. On s1: v1 pending carving + depth, v3 confirmed paint + figurehead, v2 confirmed figurehead (talked-over question), v5 pending ship_model, v4/v6 none. Provisional (Joey to confirm): **Q6** a rescinded layer isn't reopened by the same evidence within the stop, but an explicit point/ask does re-confirm it (`POINT_ASK_REOPENS_RESCINDED=True`) · **Q7** a question with no pointed feature confirms `exhibit_interest` on the current stop · confidence values (`LAYER_EVENT_CONF`, `SEED_LAYER_CONF`, `PENDING_WEIGHT`, `LAMBDA_DOMINANCE`) are placeholders.
- 2026-11-11: **Task 3 done.** `data/content/{figurehead,ship_model,compass}.json` + `sdc/content.py` (loader, validator incl. a D7 phrase lint, keyword Q&A) + `tests/test_content.py`. Core script with gaze/gesture cues per segment, open question, 4–6 additions tagged `type` (detail/depth/neighbour) and `serves` (`{kind, target}` layers, read by s_i(a)), canned Q&A answering all five s1 questions. Content is invented (fictional ship *Marigold*). Open: **Q8** addition lead-ins are neutral ("One more thing about the carving…") and never mention visitors' behaviour, which is stricter than D7's "A few of you seem curious…" example, since that phrasing would single out a lone lingerer.
- 2026-11-11: **Task 4 done.** `sdc/decision.py`, `sdc/loop.py`, `run_loop.py`, `tests/test_decision.py`. Open loop on s1: v2 excluded at 54 s → glance + turn, step back at 60 s, pause + gaze when talked over at 73 s, then their question is answered to the group; 2 additions (both taken up), all 5 questions answered, v3 ends with the highest credit (weight 0.29), no unresolved episodes, next stop = P12 two-way choice (no confirmed interest in either option). Open: **Q9** D1's next-stop filter ("an exhibit a child can't see") conflicts with D4 (child/adult only seeds baselines), and the gallery has no access data, so `would_exclude()` is a no-op hook · **Q10** credit k_i grows when a question is answered or an addition is taken up (not on delivery alone) · **Q11** questions are answered at the next speech gap in any phase, and answers don't count toward the P11 cap · **Q12** the next-stop planner counts confirmed layers only (per §6), so v5's pending drift doesn't steer it · open-loop artifacts until task 5: talked-over at 72 s comes from the mock's scripted robot speech; uptake is trivially true for someone already lingering.
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
- 2026-11-12: **Q17 answered (Joey): cap the wait and count it.** Wait up to `WAIT_MAX_S` (tunable, 45 s), then start; late arrivals go through the normal exclusion handler; `measures.falling_behind.stops_started_without_everyone` / `missing` record it as a floor miss (s2: 0). **Q9–Q17 answered** (Q6–Q8 still provisional, see §8). Remaining open: tour-close owner, interface v0.1 sign-off (Joey/Jay). Vault to update (Joey): §6.4/D1 (Q9), Implementation credit example (Q10), D10 falling-behind note (Q14), P12 agreed (Q16). **Next: task 9 (baseline comparison), then optional s3/s4.**
- 2026-11-12: **Task 9 done.** `sdc/policies.py` (ours · one_size, Burgard 1999 · engagement, Lin 2024 — switches over the same decision layer), `compare_policies.py` → `results/policies.md` (gitignored), `tests/test_policies.py`. Results (simulated visitors, mean over 20 s1 / 10 s2 seeds): P13 unresolved 0 (ours) vs 0.17 (both baselines: the child stays excluded); steering uptake s1 0.72 / 0.62 / 0.69, s2 0.71 / 0.48 / 0.71; dominance share s1 0.57 / 0.80 / 0.62, s2 0.41 / 0.83 / 0.45; time to resolve 2.4 s vs never (position barrier); baselines start stops without the slow walker. Misread rate mixed (ours 0.39 vs engagement 0.17 in s1, 0.23 vs 0.43 in s2). Caveat for the paper: sim rules (e.g. the child only joins when invited) drive the exclusion result; this demonstrates mechanisms, not real-visitor effects. **Next (optional): s3_dominant, s4_misread; paper figures.**
- 2026-11-14: **Handoff reorganised for the paper phase.** HANDOFF rewritten (status, rules → code, system summary, results, decisions, paper inputs); `run_tests.py` added; README/CLAUDE.md commands updated. Correction: Q6–Q8 were never answered (an earlier entry said all were). s3/s4 and figures deferred (Joey). **Next: outline the paper (§9).**
- 2026-11-14: **Q6–Q8 answered (Joey): keep the current defaults.** Q6 an explicit question re-confirms a rescinded guess (`POINT_ASK_REOPENS_RESCINDED=True`) · Q7 an unpointed question confirms interest in the current exhibit · Q8 neutral addition lead-ins. No code change. **All design questions Q1–Q17 answered.** Vault note for Joey: D7's example phrasing ("A few of you seem curious…") isn't used (Q8).
