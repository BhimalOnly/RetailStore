"""Every generic "home" (rail tile, toolbar home icon, typed /desk/home URLs) returns retail users to
Retail Store, never Frappe's Setup shell or Apps launcher. System Manager keeps Frappe's home.
Run:  /path/to/pw/bin/python browser_home.py"""
from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
PWD = "RetailDemo#2026"
fails = []


def check(name, ok, detail=""):
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
	if not ok:
		fails.append(name)


with sync_playwright() as p:
	br = p.chromium.launch()
	for user in ("owner", "admin", "manager.downtown", "cashier.downtown", "wh.attendant", "accountant"):
		ctx = br.new_context(viewport={"width": 1300, "height": 850})
		page = ctx.new_page()
		ctx.request.post(f"{B}/api/method/login", data={"usr": user + "@demo.example", "pwd": PWD})
		page.goto(B + "/desk/retail-store")
		page.wait_for_selector("#st-icon-rail .st-rail-brand", state="attached", timeout=60000)
		page.wait_for_timeout(2500)
		page.evaluate("document.querySelector('#st-icon-rail .st-rail-brand').click()")  # hidden now; the redirect is the fallback
		page.wait_for_timeout(3000)
		check(f"{user}: rail tile returns to Retail Store", page.url.rstrip("/").endswith("/desk/retail-store"), page.url)
		for path in ("/desk/home", "/desk/setup/home", "/desk/build/desktop"):
			page.goto(B + path)
			page.wait_for_timeout(4500)
			check(f"{user}: {path} lands in Retail Store", page.url.rstrip("/").endswith("/desk/retail-store"), page.url)
		body = page.inner_text("body")
		check(f"{user}: no ERPNext/Frappe HR app tiles or Not permitted dialog", "Frappe HR" not in body and "Not permitted" not in body)
	# avatar menu and rail: no app names / versions, one Retail Store icon, for everyone but System Manager
	for user in ("owner", "cashier.downtown", "accountant"):
		ctx = br.new_context(viewport={"width": 1300, "height": 850})
		page = ctx.new_page()
		ctx.request.post(f"{B}/api/method/login", data={"usr": user + "@demo.example", "pwd": PWD})
		page.goto(B + "/desk/retail-store")
		page.wait_for_selector("#st-user-btn", timeout=60000)
		page.wait_for_timeout(2500)
		page.click("#st-user-btn")
		page.wait_for_timeout(800)
		menu = page.inner_text("body")
		check(f"{user}: avatar menu has no Installed Apps / versions", page.locator(".st-ud-app-tile").count() == 0 and "Installed Apps" not in menu and "16.5" not in menu)
		versions = page.evaluate("()=>Object.keys(frappe.boot.versions||{}).length")
		check(f"{user}: boot carries no app versions", versions == 0, versions)
		api = ctx.request.get(f"{B}/api/method/frappe.utils.change_log.get_versions")
		check(f"{user}: get_versions API returns nothing", api.ok and api.json().get("message") in ({}, None), api.text()[:80])
		check(f"{user}: no Reset Desktop Layout in the avatar menu", page.locator("[data-action=reset-layout]:visible").count() == 0)
		page.keyboard.press("Escape")
		check(f"{user}: top brand tile hidden (one Retail Store icon)", page.locator("#st-icon-rail .st-rail-brand:visible").count() == 0)
		rail = page.inner_text("#st-icon-rail")
		check(f"{user}: no Stock/Selling/Accounts icons in the rail", not any(w in rail for w in ("Stock", "Selling", "Accounts")) and page.locator(".st-rail-modules").count() == 0, rail)
		page.click("#st-options-btn")
		page.wait_for_timeout(800)
		panel = page.inner_text("#st-options-panel")
		check(f"{user}: All Options is just Appearance (no theme-profile names, no workspace list)", "Appearance" in panel.title() and "Frappe Default" not in panel and "Solvronix" not in panel and "Workspaces" not in panel.title(), panel[:200])
		page.keyboard.press("Escape")
		page.wait_for_timeout(500)
		page.click("#st-tb-quicknav button >> nth=0")
		page.wait_for_timeout(3000)
		check(f"{user}: toolbar home icon returns to Retail Store", page.url.rstrip("/").endswith("/desk/retail-store"), page.url)
	# owner/admin: what the raw Stock/Selling/Accounts shells held is now in the Retail Store sidebar
	for user in ("owner", "admin"):
		ctx = br.new_context(viewport={"width": 1300, "height": 850})
		page = ctx.new_page()
		ctx.request.post(f"{B}/api/method/login", data={"usr": user + "@demo.example", "pwd": PWD})
		page.goto(B + "/desk/retail-store")
		page.wait_for_selector(".body-sidebar-container, .sidebar-item-container", timeout=60000)
		page.wait_for_timeout(2500)
		side = page.inner_text("body")
		if user == "owner":
			check("owner: Back Office section with Online Orders and Payments", "back office" in side.lower() and "online orders" in side.lower() and "payments" in side.lower(), side[:300])
			page.get_by_text("Online Orders", exact=False).first.click()
			page.wait_for_timeout(4000)
			check("owner: Online Orders opens inside Retail Store (sidebar stays)", "sales-order" in page.url and "back office" in page.inner_text("body").lower(), page.url)
			check("owner: Profit & Loss and Balance Sheet offered", "profit & loss" in page.inner_text("body").lower() and "balance sheet" in page.inner_text("body").lower())
			page.get_by_text("Profit & Loss", exact=False).first.click()
			page.wait_for_selector(".report-wrapper, .query-report", timeout=60000)
			page.wait_for_timeout(5000)
			body = page.inner_text("body")
			check("owner: Profit & Loss opens as a report inside Retail Store", "/desk/retail-store/query-report/Profit" in page.url and "back office" in body.lower() and "Not permitted" not in body and "Not Permitted" not in body, page.url)
			check("owner: the report is not a raw Accounting shell", "chart of accounts" not in body.lower().split("back office")[0])
			page.screenshot(path="shots/home-pnl.png")
		else:  # Store Admin holds no Sales Order / Payment Entry rights, so is not offered them
			check("admin: not offered Online Orders / Payments / Profit & Loss", "online orders" not in side.lower() and "payments" not in side.lower() and "profit & loss" not in side.lower())
	# rail hidden when the user has one app; brand mark beside the company name; "Appearance" button
	for user, single in (("owner", True), ("admin", True), ("manager.downtown", True), ("cashier.downtown", True), ("wh.attendant", True), ("accountant", False)):
		ctx = br.new_context(viewport={"width": 1300, "height": 800})
		page = ctx.new_page()
		ctx.request.post(f"{B}/api/method/login", data={"usr": user + "@demo.example", "pwd": PWD})
		page.goto(B + "/desk/retail-store")
		page.wait_for_selector("#st-options-btn", timeout=60000)
		page.wait_for_selector("#st-company-header", timeout=60000)
		page.wait_for_timeout(2500)
		rail_visible = page.locator("#st-icon-rail:visible").count() == 1
		check(f"{user}: icon rail {'hidden' if single else 'kept'}", rail_visible != single)
		mark = page.locator("#st-company-header .rs-brand-mark").count()
		check(f"{user}: brand mark {'beside the company name' if single else 'not duplicated (rail shows it)'}", (mark == 1) == single, mark)
		if single:
			src = page.evaluate("document.querySelector('#st-company-header .rs-brand-mark').src")
			ok_img = page.evaluate("document.querySelector('#st-company-header .rs-brand-mark').naturalWidth > 0")
			check(f"{user}: brand mark image loads", ok_img, src)
			side = page.locator(".body-sidebar").first.bounding_box()
			check(f"{user}: sidebar sits flush left once the rail is gone", side and side["x"] < 8, side)
			main = page.locator(".layout-main-section, .page-container, .desk-body").first.bounding_box()
			check(f"{user}: page content starts right of the sidebar (no overlap)", main and side and main["x"] >= side["x"] + side["width"] - 2, (main, side))
		label = page.inner_text("#st-options-btn .st-options-label").strip()
		check(f"{user}: toolbar button reads Appearance", label == "Appearance", label)
		page.click("#st-options-btn")
		page.wait_for_timeout(800)
		head = page.inner_text("#st-options-panel-head")
		check(f"{user}: panel heading reads Appearance, once", "Appearance" in head and "All Options" not in head and page.locator("#st-op-appearance .st-op-section-head:visible").count() == 0, head)
		page.keyboard.press("Escape")
	# narrow window: still loads, rail hidden, no sideways scroll
	ctx = br.new_context(viewport={"width": 700, "height": 800})
	page = ctx.new_page()
	ctx.request.post(f"{B}/api/method/login", data={"usr": "owner@demo.example", "pwd": PWD})
	page.goto(B + "/desk/retail-store")
	page.wait_for_selector(".ce-block", timeout=60000)
	page.wait_for_timeout(2500)
	check("narrow window: rail hidden and no sideways scroll", page.locator("#st-icon-rail:visible").count() == 0 and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2"))
	page.screenshot(path="shots/home-narrow.png")
	ctx = br.new_context(viewport={"width": 1300, "height": 850})
	page = ctx.new_page()
	ctx.request.post(f"{B}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	page.goto(B + "/desk/retail-store")
	page.wait_for_selector("#st-user-btn", timeout=60000)
	page.wait_for_timeout(2000)
	page.click("#st-user-btn")
	page.wait_for_timeout(800)
	check("System Manager still sees Installed Apps", page.locator(".st-ud-app-tile").count() >= 3)
	check("System Manager still sees the brand tile", page.locator("#st-icon-rail .st-rail-brand:visible").count() == 1)
	check("System Manager keeps the rail with several apps", page.locator("#st-icon-rail .st-rail-app:visible").count() >= 3)
	check("System Manager's button still reads All Options", page.inner_text("#st-options-btn .st-options-label").strip() == "All Options")
	check("System Manager gets no brand mark beside the name", page.locator("#st-company-header .rs-brand-mark").count() == 0)
	page.keyboard.press("Escape")
	page.goto(B + "/desk/setup/home")
	page.wait_for_timeout(4500)
	check("System Manager still reaches Frappe's own home", "/desk/setup/home" in page.url, page.url)
	print("\nFAILURES:", fails or "none")
