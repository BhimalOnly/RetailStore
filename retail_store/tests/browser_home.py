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
		page.wait_for_selector("#st-icon-rail .st-rail-brand", timeout=60000)
		page.wait_for_timeout(2500)
		page.click("#st-icon-rail .st-rail-brand")
		page.wait_for_timeout(3000)
		check(f"{user}: rail tile returns to Retail Store", page.url.rstrip("/").endswith("/desk/retail-store"), page.url)
		for path in ("/desk/home", "/desk/setup/home", "/desk/build/desktop"):
			page.goto(B + path)
			page.wait_for_timeout(4500)
			check(f"{user}: {path} lands in Retail Store", page.url.rstrip("/").endswith("/desk/retail-store"), page.url)
		body = page.inner_text("body")
		check(f"{user}: no ERPNext/Frappe HR app tiles or Not permitted dialog", "Frappe HR" not in body and "Not permitted" not in body)
	ctx = br.new_context(viewport={"width": 1300, "height": 850})
	page = ctx.new_page()
	ctx.request.post(f"{B}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	page.goto(B + "/desk/setup/home")
	page.wait_for_timeout(4500)
	check("System Manager still reaches Frappe's own home", "/desk/setup/home" in page.url, page.url)
	print("\nFAILURES:", fails or "none")
