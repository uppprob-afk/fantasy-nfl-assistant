"""Check the in-browser Trade Lab engine (site/lab.js) agrees with the Python pipeline.

    uv run python -m nfl_assistant.run                      # build site/data first
    uv run --with playwright python tools/lab_parity.py     # uses your installed Chrome

Compares every team's rest-of-season value, each suggested trade's gains, and playoff
odds (within simulation noise). Exits non-zero if anything disagrees.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"


def main() -> int:
    trades = json.loads((DATA / "trades.json").read_text())
    outlook = json.loads((DATA / "outlook.json").read_text())
    ideas = [{"partner": t["roster_id"], "give": [p["id"] for p in t["give"]],
              "get": [p["id"] for p in t["get"]], "my": t["my_gain"], "their": t["their_gain"]}
             for t in trades["ideas"]]
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto((ROOT / "site" / "index.html").as_uri())
        page.wait_for_timeout(500)
        check = page.evaluate("NFLLab.create(NFL_DATA.lab).selfCheck()")
        print(f"team values: max difference {check['maxDiff']:.2f} pts")
        ok &= check["ok"]
        res = page.evaluate("""(ideas) => { const E = NFLLab.create(NFL_DATA.lab);
            return ideas.map(i => { const r = E.evaluateTrade(i.partner, i.give, i.get, {sims: 500});
              return [r.gainMe, r.gainThem]; }); }""", ideas)
        for i, (mine, theirs) in zip(ideas, res):
            same = abs(mine - i["my"]) <= 0.2 and abs(theirs - i["their"]) <= 0.2
            ok &= same
            print(f"trade gains python {i['my']}/{i['their']} vs browser {mine}/{theirs}: {'ok' if same else 'MISMATCH'}")
        sim = page.evaluate("NFLLab.create(NFL_DATA.lab).simulate({}, {n: 10000})")
        worst = max(abs(t["odds"] - sim[str(t["roster_id"])]["odds"]) for t in outlook["playoffs"]["teams"])
        print(f"playoff odds: max difference {100 * worst:.1f} percentage points")
        ok &= worst < 0.03
        browser.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
