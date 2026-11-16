"""Package boundaries, checked on the source text (standard library only, so this runs everywhere)."""
import glob
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _imports(path):
    return re.findall(r"^\s*(?:from|import)\s+([\w.]+)", open(path).read(), re.M)


def test_sdc_never_imports_perception():
    for path in glob.glob(os.path.join(REPO, "sdc", "*.py")):
        assert not any(m.split(".")[0] == "perception" for m in _imports(path)), path


def test_perception_uses_no_yaml_and_no_files_from_jays_repo():
    for path in glob.glob(os.path.join(REPO, "perception", "*.py")):
        mods = {m.split(".")[0] for m in _imports(path)}
        assert not mods & {"yaml", "modules", "flask", "pydantic"}, (path, mods)


def test_perception_imports_only_the_schema_from_sdc():
    for path in glob.glob(os.path.join(REPO, "perception", "*.py")):
        sdc = [m for m in _imports(path) if m.split(".")[0] == "sdc"]
        assert sdc in ([], ["sdc"]), (path, sdc)
        if sdc:
            assert "from sdc import schema\n" in open(path).read(), path
