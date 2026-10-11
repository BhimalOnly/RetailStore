"""Browser click-through of the collapsible sidebar (#18) and the Retail Store home page (#19).

Run:  /path/to/pw/bin/python browser_home_page.py   Screenshots land in ./shots/homepage-*.png
"""
import os
import re
from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
PWD = "RetailDemo#2026"
OUT = "shots"
os.makedirs(OUT, exist_ok=True)
fails = []


def check(name, ok, detail=""):
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
	if not ok:
		fails.append(name)


def open_home(br, user, width=1300):
	ctx = br.new_context(viewport={"width": width, "height": 850})
	page = ctx.new_page()
	ctx.request.post(f"{B}/api/method/login", data={"usr": user + "@demo.example", "pwd": PWD})
	page.goto(B + "/desk/retail-store")
	page.wait_for_selector(".ce-block", timeout=60000)
	page.wait_for_timeout(4500)
	return ctx, page


def greeting(page):
	return page.evaluate("""()=>{const e=[...document.querySelectorAll('*')].find(x=>x.tagName.toLowerCase().startsWith('custom-block-'));
		if(!e||!e.shadowRoot) return null;
		const m=e.shadowRoot.querySelector('.rs-greet-main'), s=e.shadowRoot.querySelector('.rs-greet-sub');
		return [m&&m.textContent, s&&s.textContent]}""")


def number_cards(page):
	return page.evaluate("()=>[...document.querySelectorAll('.number-widget-box')].map(w=>w.innerText.replace(/\\s+/g,' ').trim())")


def tiles(page):
	return page.evaluate("()=>[...document.querySelectorAll('.shortcut-widget-box .widget-title')].map(w=>w.innerText.trim())")


with sync_playwright() as p:
	br = p.chromium.launch()

	# ---- #19 home page, per role
	expect = {
		"owner": ({"Sales today", "Requests waiting"}, {"Sales", "Request Transfer"}),
		"manager.downtown": ({"Sales today", "Requests waiting"}, {"Sales", "Request Transfer"}),
		"wh.attendant": ({"Requests waiting"}, {"Request Transfer"}),
		"cashier.downtown": (set(), set()),
	}
	for user, (cards, gone) in expect.items():
		ctx, page = open_home(br, user)
		g = greeting(page)
		check(f"{user}: greeting says Good morning/afternoon/evening, first name", g and re.match(r"Good (morning|afternoon|evening), \S+", g[0] or ""), g)
		check(f"{user}: greeting subtext has store/brand and today's date", g and g[1] and " · " in g[1] and re.search(r"\d", g[1]), g)
		nc = number_cards(page)
		titles = {t for t in cards if any(t in n for n in nc)}
		check(f"{user}: number cards = {sorted(cards) or 'none'}", titles == cards and len(nc) == len(cards), nc)
		for n in nc:
			check(f"{user}: card shows a figure ({n[:30]})", re.search(r"\d", n), n)
		tl = tiles(page)
		check(f"{user}: replaced tiles gone ({sorted(gone) or 'n/a'})", not (gone & set(tl)), tl)
		if user == "cashier.downtown":
			check("cashier keeps the simple tiles", "Point of Sale" in tl and "Customer" in tl, tl)
		check(f"{user}: no 'Not permitted' / error dialog", "Not permitted" not in page.inner_text("body") and page.locator(".msgprint:visible, .modal.show").count() == 0)
		page.screenshot(path=f"{OUT}/homepage-{user}.png")

	# ---- #18 collapsible sidebar
	for user, single in (("owner", True), ("cashier.downtown", True), ("accountant", False)):
		ctx, page = open_home(br, user)
		w0 = page.locator(".body-sidebar").first.bounding_box()["width"]
		check(f"{user}: header chevron present", page.locator("#st-company-header .rs-sidebar-toggle:visible").count() == 1)
		check(f"{user}: edge arrow always visible", page.evaluate("getComputedStyle(document.querySelector('.sidebar-collapse-arrow')).opacity") == "1")
		page.click("#st-company-header .rs-sidebar-toggle")
		page.wait_for_timeout(1200)
		w1 = page.locator(".body-sidebar").first.bounding_box()["width"]
		check(f"{user}: chevron collapses the sidebar to an icon strip", w1 < 100 < w0, (w0, w1))
		mark = page.locator("#st-company-header .rs-brand-mark:visible").count()
		name = page.locator("#st-company-header .st-company-name:visible").count()
		if single:
			check(f"{user}: collapsed shows the logo only (no company name)", mark == 1 and name == 0, (mark, name))
		page.screenshot(path=f"{OUT}/homepage-{user}-collapsed.png")
		page.reload()
		page.wait_for_selector(".ce-block", timeout=60000)
		page.wait_for_timeout(3000)
		check(f"{user}: collapsed state is remembered after a reload", page.locator(".body-sidebar").first.bounding_box()["width"] < 100)
		if single:
			page.click("#st-company-header")
		else:
			page.click(".sidebar-collapse-arrow")
		page.wait_for_timeout(1200)
		check(f"{user}: expands again", page.locator(".body-sidebar").first.bounding_box()["width"] > 200)

	# ---- narrow window
	ctx, page = open_home(br, "owner", width=700)
	check("narrow window: home page loads, greeting visible, no sideways scroll", greeting(page) and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2"))
	page.screenshot(path=f"{OUT}/homepage-narrow.png")
	print("\nFAILURES:", fails or "none")
