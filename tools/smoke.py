"""Browser smoke test for the static site: opens every screen at phone width (light and dark),
taps the main buttons and fails on any page error, empty screen or sideways scroll.

    uv run python -m nfl_assistant.anonymize          # builds demo/ (never commit it)
    uv run --with playwright python tools/smoke.py     # needs Google Chrome installed

Optional argument: path to the site folder (default demo/). Not part of pytest: it needs a
browser and real-shaped data.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(sys.argv[1] if len(sys.argv) > 1 else "demo").resolve()
SUBS = {"home": ["home"], "league": ["league"], "players": ["players"],
        "moves": ["faab", "news", "trades", "lab", "nfl"], "model": ["model"]}
problems: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        problems.append(what)


def run(page, scheme: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(SITE.joinpath("index.html").as_uri())
    page.wait_for_selector("#tab-home .hsec")
    wide = lambda: page.evaluate("document.documentElement.scrollWidth") <= 391

    # opening straight onto a deeper screen builds it
    page.goto(SITE.joinpath("index.html").as_uri() + "#lab")
    page.wait_for_selector("#lab-suggest")
    check(page.locator("#tab-lab").is_visible(), f"{scheme}: opens straight on #lab")
    page.goto(SITE.joinpath("index.html").as_uri() + "#home")
    page.wait_for_selector("#tab-home .hsec")

    # every screen builds on first open and has content
    for sec, subs in SUBS.items():
        page.locator(f'#tabs button[data-tab="{sec}"]').click()
        for sub in subs:
            if len(subs) > 1:
                page.locator(f'#subnav button[data-sub="{sub}"]').click()
            page.wait_for_timeout(150)
            n = len(page.locator(f"#tab-{sub}").inner_text().strip())
            check(n > 50 and wide(), f"{scheme}: {sub} screen ({n} chars)")
    page.goto(SITE.joinpath("index.html").as_uri() + "#glossary")
    page.wait_for_timeout(200)
    check(page.locator("#tab-glossary").inner_text().count("\n") > 10, f"{scheme}: glossary")

    # Home views
    page.locator('#tabs button[data-tab="home"]').click()
    for v in ["roster", "startsit", "lineups", "playoffs"]:
        page.locator(f'#home-seg button[data-view="{v}"]').click()
        page.wait_for_timeout(150)
        check(len(page.locator("#home-body").inner_text()) > 50 and wide(), f"{scheme}: Home → {v}")

    # Hold before the Lab or Trades screens exist, then Home's recap link
    page.locator('#home-seg button[data-view="roster"]').click()
    page.locator("#tab-home details.prow-d > summary").first.click()
    hold = page.locator('#tab-home details.prow-d[open] [data-act="hold"]')
    if hold.count():
        hold.first.click()
        page.wait_for_timeout(200)
        check(not page.locator("#toast").is_hidden(), f"{scheme}: Hold works")
        page.click("#toast-undo")
    if page.locator('#tab-home [data-act="recap"]').count():
        page.locator('#tab-home [data-act="recap"]').first.click()
        page.wait_for_timeout(300)
        check(page.locator("#tab-league").is_visible() and "Your week" in page.locator("#tab-league").inner_text(), f"{scheme}: recap link")
        page.locator('#tabs button[data-tab="home"]').click()

    # player sheet from a tappable name, closed by Back
    page.locator('#home-seg button[data-view="roster"]').click()
    name = page.locator("#tab-home .plink").first
    if name.count():
        name.click()
        page.wait_for_timeout(400)
        check(page.evaluate("document.getElementById('player-sheet').open"), f"{scheme}: player sheet opens")
        page.go_back()
        page.wait_for_timeout(200)
        check(not page.evaluate("document.getElementById('player-sheet').open"), f"{scheme}: Back closes it")

    # League views
    page.locator('#tabs button[data-tab="league"]').click()
    for v in ["teams", "recap", "trades", "standings", "race", "power"]:
        page.locator(f'#league-seg button[data-view="{v}"]').click()
        page.wait_for_timeout(150)
        check(len(page.locator("#tab-league").inner_text()) > 100 and wide(), f"{scheme}: League → {v}")

    # Trade Lab: find trades, star one, copy one, load one
    page.locator('#tabs button[data-tab="moves"]').click()
    page.locator('#subnav button[data-sub="lab"]').click()
    page.click("#lab-suggest")
    page.wait_for_selector("#lab-offers .offer", timeout=20000)
    check(page.locator("#lab-offers .offer").count() > 0, f"{scheme}: Lab finds offers")
    page.locator('#lab-offers [data-act="star"]').first.click()
    check("(1)" in page.locator("#lab-short summary").inner_text(), f"{scheme}: shortlist saves")
    page.locator('#lab-offers [data-act="copy-offer"]').first.click()
    page.wait_for_timeout(200)
    check(not page.locator("#toast").is_hidden(), f"{scheme}: copy offer responds")
    page.locator("#lab-offers [data-offer]").first.click()
    page.wait_for_timeout(1500)
    check("You" in page.locator("#lab-result").inner_text(), f"{scheme}: offer loads into the Lab")

    # FAAB budget plan
    page.locator('#subnav button[data-sub="faab"]').click()
    page.wait_for_timeout(200)
    check("Keep in reserve".upper() in page.locator("#tab-faab .faab-plan").inner_text().upper(), f"{scheme}: FAAB budget plan")

    # deadline plan (only while the deadline is still ahead)
    page.locator('#subnav button[data-sub="trades"]').click()
    page.wait_for_timeout(200)
    if page.locator('#tab-trades [data-act="deadline-build"]').count():
        page.locator('#tab-trades [data-act="deadline-build"]').first.click()
        page.wait_for_selector("#tab-trades .deadline .offer, #tab-trades .deadline p.subtle", timeout=60000)
        check(page.locator("#tab-trades .deadline").count() == 1 and wide(), f"{scheme}: deadline plan builds")

    # Players search
    page.locator('#tabs button[data-tab="players"]').click()
    page.wait_for_timeout(200)
    check(page.locator("#ps-results").inner_text().strip() != "", f"{scheme}: player search results")

    check(not errors, f"{scheme}: no page errors {errors[:2]}")


def main() -> None:
    if not SITE.joinpath("index.html").exists():
        sys.exit(f"No site at {SITE}. Run: uv run python -m nfl_assistant.anonymize")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for scheme in ("light", "dark"):
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme=scheme)
            run(ctx.new_page(), scheme)
            ctx.close()
        browser.close()
    print(f"\n{len(problems)} problem(s)" if problems else "\nAll smoke checks passed.")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
