"""Browser click-through of POS exit, the stale-shift block and the simplified POS Closing Entry.

Changes shifts, so it restores them at the end. Run:
    /path/to/pw/bin/python browser_pos_shift.py        (site running; demo data; cwd for ./shots)
"""
import os
import subprocess
import time
from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
PWD = "RetailDemo#2026"
OUT = "shots"
BENCH = os.environ.get("BENCH", "/home/bhimall/benches/retail-store-bench")
os.makedirs(OUT, exist_ok=True)
fails = []


def check(name, ok, detail=""):
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
	if not ok:
		fails.append(name)


def bench(fn):
	subprocess.run(["bench", "--site", "retail.localhost", "execute", fn], cwd=BENCH, capture_output=True, timeout=240)


def login(br, user, width=1300):
	ctx = br.new_context(viewport={"width": width, "height": 900})
	page = ctx.new_page()
	assert ctx.request.post(f"{B}/api/method/login", data={"usr": user + "@demo.example", "pwd": PWD}).status == 200
	return ctx, page


def open_pos(page):
	page.goto(B + "/desk/point-of-sale")
	page.wait_for_selector(".rs-pos-back, .rs-stale-dialog", timeout=90000)
	page.wait_for_timeout(3000)


def count_row(page):
	"""Type the expected amount into Counted for the first payment row (a real cell edit)."""
	cell = page.locator("[data-fieldname=payment_reconciliation] .grid-row [data-fieldname=closing_amount]").first
	cell.click()
	page.wait_for_timeout(700)
	page.keyboard.press("Control+a")
	page.keyboard.type("0")
	page.keyboard.press("Tab")
	page.wait_for_timeout(700)


with sync_playwright() as p:
	br = p.chromium.launch()
	bench("retail_store.demo.refresh_pos_openings")
	bench("retail_store.tests.pos_shift_setup.ensure_open")

	# ---- 1. back to Retail Store, with the unpaid-cart confirmation
	ctx, page = login(br, "cashier.downtown")
	open_pos(page)
	check("POS has a visible 'Retail Store' back control", page.locator(".rs-pos-back:visible").count() == 1)
	page.screenshot(path=f"{OUT}/shift-1-pos-back.png")
	page.locator(".item-wrapper").first.click()
	page.wait_for_timeout(1500)
	if page.locator(".modal.show").count():  # a variant picker: choose the first option
		page.keyboard.press("Escape")
		page.wait_for_timeout(500)
		page.locator(".item-wrapper:not(.rs-template-card)").first.click()
		page.wait_for_timeout(1200)
	items_in_cart = page.evaluate("(window.cur_pos && cur_pos.frm.doc.items || []).length")
	if items_in_cart:
		page.click(".rs-pos-back")
		page.wait_for_timeout(800)
		check("unpaid cart: asks before leaving", "Leave this sale" in page.inner_text(".modal.show"))
		page.screenshot(path=f"{OUT}/shift-2-leave-confirm.png")
		page.locator(".modal.show").get_by_role("button", name="No").click()
		page.wait_for_timeout(1200)
		check("answering No keeps the sale on screen", "point-of-sale" in page.url)
		page.click(".rs-pos-back")
		page.wait_for_timeout(1200)
		page.locator(".modal.show").get_by_role("button", name="Yes").click()
		page.wait_for_timeout(2500)
		check("answering Yes goes to Retail Store home", page.url.rstrip("/").endswith("/desk/retail-store"), page.url)
	else:
		check("could add an item to the cart for the confirmation test", False)
	bench("retail_store.demo.refresh_pos_openings")
	open_pos(page)
	page.click(".rs-pos-back")
	page.wait_for_timeout(2500)
	check("empty cart: back control leaves straight away", page.url.rstrip("/").endswith("/desk/retail-store"), page.url)

	# ---- 2. stale shift: blocked, one action, lands back in POS
	bench("retail_store.tests.pos_shift_setup.make_stale")
	ctx, page = login(br, "cashier.downtown")
	page.goto(B + "/desk/point-of-sale")
	page.wait_for_selector(".rs-stale-dialog .modal-title", timeout=90000)
	page.wait_for_timeout(1500)
	dlg = page.inner_text(".rs-stale-dialog")
	check("stale shift: branded dialog explains and offers Close shift", "An earlier shift is still open" in dlg and "Close shift" in dlg, dlg)
	check("stale shift: the dialog has no close (X) button", page.locator(".rs-stale-dialog .btn-modal-close:visible").count() == 0)
	page.keyboard.press("Escape")
	page.mouse.click(300, 600)  # the backdrop
	page.wait_for_timeout(800)
	check("stale shift: Escape / clicking outside does not dismiss it", page.locator(".rs-stale-dialog.show, .rs-stale-dialog:visible").count() >= 1)
	page.screenshot(path=f"{OUT}/shift-3-stale-dialog.png")
	page.locator(".rs-stale-dialog").get_by_role("button", name="Close shift").click()
	page.wait_for_selector(".form-layout", timeout=60000)
	page.wait_for_timeout(5000)
	check("closing form opens for the old shift", "pos-closing-entry" in page.url, page.url)

	# ---- 3. the simplified closing form (cashier)
	body = page.inner_text("body")
	check("cashier form: Period / User / Totals sections are collapsed away", all(w not in body for w in ("PERIOD DETAILS", "USER DETAILS", "Period Start Date", "Posting Time")), body[:300])
	check("cashier form: one-line summary shown", page.locator(".rs-close-summary").count() == 1 and "Downtown" in page.inner_text(".rs-close-summary"))
	hdr = page.inner_text("[data-fieldname=payment_reconciliation]")
	check("cashier form: columns read Expected / Counted / Difference", all(w in hdr for w in ("Expected", "Counted", "Difference")), hdr[:200])
	check("cashier form: primary button reads Close shift", "Close shift" in page.locator(".page-head:visible").first.inner_text(), page.locator(".page-head:visible").first.inner_text()[:200])
	check("cashier form: plain-language instruction shown", "Count what is in the drawer" in body)
	page.screenshot(path=f"{OUT}/shift-4-closing-form.png")
	count_row(page)
	page.locator(".page-head:visible button:has-text('Close shift')").first.click()
	page.wait_for_timeout(1200)
	page.locator(".modal.show").get_by_role("button", name="Yes").click()
	page.wait_for_url("**/point-of-sale", timeout=90000)
	check("forced close of a stale shift lands back in POS", "point-of-sale" in page.url, page.url)
	page.wait_for_timeout(5000)
	body = page.inner_text("body")
	check("...and POS now asks to open today's shift", "Create POS Opening Entry" in body or "Opening" in body, body[:200])
	page.screenshot(path=f"{OUT}/shift-5-after-stale-close.png")
	bench("retail_store.tests.pos_shift_setup.ensure_open")

	# ---- 4. deliberate end-of-day close lands on Retail Store home
	ctx, page = login(br, "cashier.downtown")
	open_pos(page)
	page.keyboard.press("Shift+Control+c")
	page.wait_for_selector(".form-layout", timeout=60000)
	page.wait_for_timeout(5000)
	count_row(page)
	page.locator(".page-head:visible button:has-text('Close shift')").first.click()
	page.wait_for_timeout(1200)
	page.locator(".modal.show").get_by_role("button", name="Yes").click()
	page.wait_for_url("**/desk/retail-store", timeout=90000)
	check("end-of-day Close the POS lands on Retail Store home", page.url.rstrip("/").endswith("/desk/retail-store"), page.url)
	bench("retail_store.tests.pos_shift_setup.ensure_open")

	# ---- 5. managers/owners keep the full form
	for user in ("manager.downtown", "owner"):
		ctx, page = login(br, user)
		page.goto(B + "/desk/pos-closing-entry/new")
		page.wait_for_selector(".form-layout", timeout=60000)
		page.wait_for_timeout(3500)
		body = page.inner_text("body")
		check(f"{user}: keeps the full closing form", "Period Details".upper() in body.upper() and "POS Opening Entry" in body, body[:200])
		check(f"{user}: no simplified summary / intro", page.locator(".rs-close-summary").count() == 0)
	page.screenshot(path=f"{OUT}/shift-6-owner-full-form.png")

	bench("retail_store.tests.pos_shift_setup.ensure_open")
	print("\nFAILURES:", fails or "none")
