"""Regenerate mock perception streams: python3 make_mock.py"""
import json, os
from sdc import mock, scenarios

HERE = os.path.dirname(os.path.abspath(__file__))
gallery = json.load(open(os.path.join(HERE, "data", "gallery.json")))
for name, make in scenarios.ALL.items():
    n = mock.write(make(), gallery,
                   os.path.join(HERE, "data", f"{name}.jsonl"),
                   os.path.join(HERE, "data", f"{name}.labels.json"))
    print(f"{name}: {n} lines")
