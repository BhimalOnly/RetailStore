"""Browser click-through of the Request Stock page and the frontline stock rules.

Seed the request first (this script sends it), then:
    bench --site retail.localhost execute retail_store.tests.check_stock_request.seed_dispatch
and re-run with SECOND=1 for the receiving half, then
    bench --site retail.localhost execute retail_store.tests.check_stock_request.clear_grants
Run:  /path/to/pw/bin/python browser_stock.py     Screenshots land in ./shots/stock-*.png
"""
import os
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


def login(br, user):
	ctx = br.new_context(viewport={"width": 1300, "height": 850})
	page = ctx.new_page()
	assert ctx.request.post(f"{B}/api/method/login", data={"usr": user, "pwd": PWD}).status == 200
	return ctx, page


with sync_playwright() as p:
	br = p.chromium.launch()
	if not (os.environ.get("SECOND") or os.environ.get("SETTINGS")):
		ctx, page = login(br, "cashier.downtown@demo.example")
		page.goto(f"{B}/desk/stock-request")
		page.wait_for_selector(".rs-find", timeout=60000)
		body = page.inner_text(".rs-sr")
		check("page opens with a product search", "What does your shop need?" in body)
		check("no Deliveries section without the right", "Deliveries on their way" not in body)
		check("no ERPNext jargon on the page", not any(w in body for w in ("Material Request", "Stock Entry", "Item rates")))
		page.fill(".rs-find", "sneaker")
		page.wait_for_selector(".rs-hit", timeout=15000)
		page.locator(".rs-hit").first.click()
		page.wait_for_selector(".rs-cart .rs-row")
		page.fill(".rs-cart .rs-qty", "3")
		page.screenshot(path=f"{OUT}/stock-1-cart.png")
		page.click(".rs-send")
		page.wait_for_function("document.querySelectorAll('.rs-cart .rs-row').length === 0", timeout=20000)
		check("cart emptied after sending", True)
		check("newest request shows as 'Waiting for approval'", "Waiting for approval" in page.locator(".rs-sr .rs-card").nth(1).locator(".rs-row").first.inner_text())
		page.screenshot(path=f"{OUT}/stock-2-sent.png")

		ctx, page = login(br, "wh.attendant@demo.example")
		page.goto(f"{B}/desk")
		page.wait_for_timeout(5000)
		side = page.inner_text("body")
		check("attendant sidebar offers Request Stock", "request stock" in side.lower())
		check("attendant sidebar hides Move Stock / Request Transfer", "move stock" not in side.lower() and "request transfer" not in side.lower())
		page.screenshot(path=f"{OUT}/stock-3-attendant.png")
	elif os.environ.get("SETTINGS"):
		# the owner gives and takes back a right through the Settings screen
		ctx, page = login(br, "owner@demo.example")
		page.goto(f"{B}/desk/retail-store-settings")
		page.get_by_text("Stock Transfers").first.click()
		page.get_by_role("button", name="Add row").click()
		page.locator("[data-fieldname=staff_grants] [data-fieldname=staff] input:visible").press_sequentially("cashier.mall", delay=60)
		page.get_by_text("cashier.mall@demo.example").first.click(timeout=15000)
		page.locator("[data-fieldname=staff_grants] [data-fieldname=permission] select:visible").select_option("Receive stock")
		page.screenshot(path=f"{OUT}/stock-6-grant-row.png")
		page.keyboard.press("Control+s")
		page.wait_for_timeout(6000)
		ctx2, page2 = login(br, "cashier.mall@demo.example")
		page2.goto(f"{B}/desk/stock-request")
		page2.wait_for_selector(".rs-find", timeout=60000)
		check("granted cashier now sees Deliveries", "Deliveries on their way" in page2.inner_text(".rs-sr"))
		ctx, page = login(br, "owner@demo.example")
		page.goto(f"{B}/desk/retail-store-settings")
		page.get_by_text("Stock Transfers").first.click()
		page.locator("[data-fieldname=staff_grants] .grid-row .grid-row-check").first.check()
		page.get_by_role("button", name="Delete").first.click()
		page.keyboard.press("Control+s")
		page.wait_for_timeout(6000)
		page2.goto(f"{B}/desk/stock-request")
		page2.wait_for_selector(".rs-find", timeout=60000)
		check("grant removed: Deliveries gone again", "Deliveries on their way" not in page2.inner_text(".rs-sr"))
	else:
		ctx, page = login(br, "cashier.downtown@demo.example")
		page.goto(f"{B}/desk/stock-request")
		page.wait_for_selector(".rs-got", timeout=60000)
		check("granted staff see the delivery", "Deliveries on their way" in page.inner_text(".rs-sr"))
		page.screenshot(path=f"{OUT}/stock-4-incoming.png")
		page.locator(".rs-got").first.click()
		page.wait_for_selector(".rs-sr .rs-empty:has-text('Nothing is on its way')", timeout=20000)
		check("delivery confirmed and cleared", True)
		page.screenshot(path=f"{OUT}/stock-5-received.png")
	print("\nFAILURES:", fails or "none")
