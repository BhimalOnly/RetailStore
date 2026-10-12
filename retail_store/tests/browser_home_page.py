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
		const q=(c)=>e.shadowRoot.querySelector(c);
		return [q('.rs-greet-main')&&q('.rs-greet-main').textContent, q('.rs-greet-eyebrow')&&q('.rs-greet-eyebrow').textContent, q('.rs-greet-date')&&q('.rs-greet-date').textContent,
			q('.rs-greet-main')&&getComputedStyle(q('.rs-greet-main')).fontFamily, q('.rs-greet-main')&&parseFloat(getComputedStyle(q('.rs-greet-main')).fontSize)]}""")


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
		check(f"{user}: eyebrow names the store/brand, date line has today's date", g and g[1] and g[2] and re.search(r"\d{4}", g[2]), g)
		check(f"{user}: heading is the large serif style", g and "Georgia" in (g[3] or "") and g[4] >= 25, g)
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

	# ---- #24 card grid: even sizes, module badges, no arrow, hover, both themes, six roles
	GRID_JS = """()=>{
		const box = (w)=>{const r=w.getBoundingClientRect(); return Math.round(r.width)+'x'+Math.round(r.height)};
		const sc=[...document.querySelectorAll('.shortcut-widget-box')], lk=[...document.querySelectorAll('.links-widget-box')];
		return {sc:sc.map(box), lk:lk.map(box),
			badged: [...sc,...lk].every(w=>w.querySelector('.rs-badge svg')),
			arrows: sc.filter(w=>[...w.querySelectorAll('svg')].some(v=>!v.closest('.rs-badge')&&getComputedStyle(v).display!=='none')).length,
			headIcons: document.querySelectorAll('.ce-header .h4 svg').length,
			overflow: document.documentElement.scrollWidth > window.innerWidth + 2}}"""
	for theme in ("light", "dark"):
		for user in ("owner", "admin", "manager.downtown", "cashier.downtown", "wh.attendant", "accountant"):
			ctx, page = open_home(br, user)
			errs = []
			page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
			page.evaluate(f"document.documentElement.setAttribute('data-theme','{theme}')")
			page.wait_for_timeout(500)
			g = page.evaluate(GRID_JS)
			tag = f"{user}/{theme}"
			check(f"{tag}: shortcut cards all the same size", len(set(g["sc"])) <= 1, g["sc"])
			check(f"{tag}: group cards all the same size", len(set(g["lk"])) <= 1, g["lk"])
			check(f"{tag}: shortcut and group cards share a column width", not g["sc"] or not g["lk"] or g["sc"][0].split("x")[0] == g["lk"][0].split("x")[0], (g["sc"][:1], g["lk"][:1]))
			check(f"{tag}: every card has a module badge with an icon", g["badged"] and (g["sc"] or g["lk"]), g)
			check(f"{tag}: no arrow glyph on shortcut cards", g["arrows"] == 0, g["arrows"])
			check(f"{tag}: section headings carry an icon", g["headIcons"] == 2, g["headIcons"])
			check(f"{tag}: no sideways scroll", not g["overflow"])
			if g["sc"]:
				first = page.locator(".shortcut-widget-box").first
				before = first.evaluate("w=>getComputedStyle(w).borderTopColor")
				first.hover()
				page.wait_for_timeout(400)
				h = first.evaluate("w=>({t:getComputedStyle(w).transform,b:getComputedStyle(w).borderTopColor,bar:getComputedStyle(w,'::before').display,title:getComputedStyle(w.querySelector('.widget-title')).color,txt:getComputedStyle(document.body).color})")
				check(f"{tag}: hover lifts the card and recolours its border", h["t"] != "none" and h["b"] != before, (before, h))
				check(f"{tag}: hover shows no theme top bar, title keeps its colour", h["bar"] == "none" and h["title"] == h["txt"], h)
			check(f"{tag}: no console errors", not errs, errs[:2])
			if user in ("owner", "cashier.downtown"):
				page.screenshot(path=f"{OUT}/homepage-grid-{user}-{theme}.png", full_page=True)
			ctx.close()

	# other workspaces are untouched (System Manager on a non-Retail workspace)
	ctx = br.new_context(viewport={"width": 1300, "height": 850})
	page = ctx.new_page()
	ctx.request.post(f"{B}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	page.goto(B + "/desk/solvronix-desk/smart-home")
	page.wait_for_timeout(6000)
	page.goto(B + "/desk/users")
	page.wait_for_timeout(5000)
	check("other workspace/page: no module badges or heading icons injected", page.locator(".rs-badge, .ce-header .h4 svg").count() == 0)
	page.goto(B + "/desk/retail-store")
	page.wait_for_selector(".rs-badge", timeout=60000)
	page.goto(B + "/desk/home")
	page.wait_for_timeout(4000)
	check("leaving Retail Store: badges are not carried to other screens", page.locator(".rs-badge").count() == 0 or "retail-store" in page.url, page.url)

	# ---- narrow window
	ctx, page = open_home(br, "owner", width=700)
	check("narrow window: home page loads, greeting visible, no sideways scroll", greeting(page) and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2"))
	page.screenshot(path=f"{OUT}/homepage-narrow.png")
	print("\nFAILURES:", fails or "none")
