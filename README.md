# hri-museum-guide

Software prototype for an HRI 2027 Student Design Competition entry: an inclusive museum guide robot for one-off tour groups. This repo is the processing loop (signal layer → decisions → behaviour → logging), running on mock perception data. There's no robot hardware.

- **Agents / new contributors:** start with [`HANDOFF.md`](HANDOFF.md).
- **Interface (perception → processing), v0.1:** `sdc/schema.py`. The human-readable spec is in the team's Obsidian notes.

```
python3 make_mock.py          # generate data/s1_one_stop.jsonl + labels
python3 tests/test_mock.py    # run tests
```

Python 3.10+, no dependencies.
