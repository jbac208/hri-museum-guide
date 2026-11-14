# hri-museum-guide

Software prototype for an HRI 2027 Student Design Competition entry: an inclusive museum guide robot for one-off tour groups. This repo is the processing loop (signal layer → profile store → decisions → content → behaviour → logging), running on mock and simulated perception. There's no robot hardware.

- **Agents / new contributors:** start with [`HANDOFF.md`](HANDOFF.md) (status, design rules, results, what's next).
- **Interface (perception → processing), v0.1:** `sdc/schema.py`. The human-readable spec is in the team's Obsidian notes.

```
python3 run_tests.py                  # regenerate mock data + run all tests
python3 eval_signals.py -v            # signal layer vs ground-truth labels
python3 run_sim.py                    # one stop, closed loop (visitors react to the robot)
python3 run_tour.py                   # three-stop tour, closed loop
python3 compare_policies.py           # ours vs one-size-fits-all vs engagement-maximising
python3 make_replay.py s2_multi_stop  # self-contained replay page in replay/
```

Python 3.10+, no dependencies.
