"""Quick smoke test for Tier 0 intent executor — run with: python test_tier0.py"""
import sys
sys.path.insert(0, ".")
from core.intent_executor import IntentExecutor

ex = IntentExecutor()

cases = [
    # (goal, should_handle)
    ("open youtube",                         True),
    ("open chrome",                          True),
    ("open brave",                           True),
    ("go to github.com",                     True),
    ("open samay raina's yt channel",        True),
    ("search for python tutorials",          True),
    ("create folder my_projects on desktop", True),
    ("open downloads folder",                True),
    ("open notion",                          True),
    ("launch vs code",                       True),
    ("open task manager",                    True),
    ("tell me a joke",                       False),  # LLM fallthrough
    ("open the budget spreadsheet",          False),  # LLM fallthrough
    ("organize my files by date",            False),  # LLM fallthrough
]

ok = fail = 0
for goal, should_handle in cases:
    r = ex.execute(goal)
    handled = r is not None
    passed = handled == should_handle
    mark = "PASS" if passed else "FAIL"
    msg = r.message if r else "-> LLM fallthrough"
    print(f"[{mark}] {goal!r:50s}  {msg}")
    if passed:
        ok += 1
    else:
        fail += 1

print(f"\n{ok}/{ok + fail} passed")
