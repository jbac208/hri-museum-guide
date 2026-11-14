"""Regenerate the mock streams and run every test file: python3 run_tests.py
(Each tests/test_*.py also runs on its own, and the suite runs under pytest.)"""
import glob, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
subprocess.run([sys.executable, os.path.join(HERE, "make_mock.py")], check=True, stdout=subprocess.DEVNULL)
failed, total = [], 0
for path in sorted(glob.glob(os.path.join(HERE, "tests", "test_*.py"))):
    r = subprocess.run([sys.executable, path], capture_output=True, text=True)
    ok = r.stdout.count("\nok") + r.stdout.startswith("ok")
    total += ok
    bad = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    print(f"{os.path.basename(path):<20} {ok:>3} ok" + (f"  {len(bad)} FAIL" if bad or r.returncode else ""))
    if bad or r.returncode:
        failed.append(path)
        print("\n".join("    " + l for l in bad) or r.stderr[-2000:])
print(f"\n{total} tests passed" + (f", {len(failed)} file(s) failing" if failed else ""))
sys.exit(1 if failed else 0)
