"""Browser check of the Online Store (webshop): a real customer buys a VARIANT and the owner fulfils it.

Needs the Online Store toggle ON (Retail Store Settings > Capabilities), the webshop app, demo data
(create_demo_data publishes the products and creates the shopper) and Playwright, see
browser_pos.py for setup. Everything it creates (quotation, order, delivery note) is cancelled and
deleted again as Administrator, which also puts the stock back, unless --keep is passed.

Run:  /tmp/pw/bin/python browser_store.py [--keep]
Exits 1 on any failed check. Screenshots land in ./shots/.
"""
import json
import os
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots"
PASSWORD = "RetailDemo#2026"
KEEP = "--keep" in sys.argv
VARIANT, WAREHOUSE = "DEMO-SNEAKER-42-WHIT", "DEMO Main Warehouse - DRC"
os.makedirs(OUT, exist_ok=True)
results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def login(ctx, user, pwd=PASSWORD):
	ctx.request.post(f"{B}/api/method/login", data={"usr": user, "pwd": pwd})


def api(ctx, path):
	r = ctx.request.get(f"{B}{path}")
	return r.json().get("data") if r.ok else None


def bin_qty(admin):
	q = urllib.parse.quote(json.dumps([["item_code", "=", VARIANT], ["warehouse", "=", WAREHOUSE]]))
	rows = api(admin, f"/api/resource/Bin?filters={q}&fields={urllib.parse.quote(json.dumps(['actual_qty', 'reserved_qty']))}")
	return (rows[0]["actual_qty"], rows[0]["reserved_qty"]) if rows else (None, None)


def create_menu(page, item):
	page.locator('.inner-group-button[data-label="Create"] button:visible').first.click()
	page.wait_for_timeout(600)
	page.evaluate(
		"""t=>{const g=[...document.querySelectorAll('.inner-group-button[data-label="Create"]')].find(e=>e.offsetParent!==null);
		g.querySelector(`a.dropdown-item[data-label="${t}"]`).click()}""",
		item,
	)
	page.wait_for_timeout(4000)


with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	login(admin, "Administrator", "admin")
	price = next(iter(api(admin, "/api/resource/Item Price?filters=" + urllib.parse.quote(json.dumps([["item_code", "=", VARIANT], ["price_list", "=", "Standard Selling"]])) + "&fields=" + urllib.parse.quote(json.dumps(["price_list_rate"]))) or [{}]), {}).get("price_list_rate")
	actual0, reserved0 = bin_qty(admin)
	print(f"desk price {price}; stock at {WAREHOUSE}: actual {actual0}, reserved {reserved0}")
	so_name = dn_name = None

	# 1. guest: the public site is the branded shop
	g = br.new_context(viewport={"width": 1300, "height": 900})
	page = g.new_page()
	page.goto(B + "/")
	page.wait_for_timeout(3500)
	check("Home page is the shop, not the login screen", page.title() == "All Products", page.title())
	check("Navbar shows the brand logo", bool(page.evaluate("document.querySelector('nav.navbar .navbar-brand img')?.src")))
	footer = page.evaluate("document.querySelector('footer')?.innerText||''")
	check("Footer carries the brand, not 'Powered by ERPNext'", "ERPNext" not in footer and footer.strip() != "", footer)
	check("Products list shows published items", all(n in page.evaluate("document.body.innerText") for n in ("DEMO Everyday Sneaker", "DEMO Cotton Tee")))
	page.screenshot(path=f"{OUT}/store-1-home.png")
	page.goto(B + "/login")
	page.wait_for_timeout(2500)
	check("Login page keeps its own theme", page.evaluate("document.body.classList.contains('sl-split')"))
	g.close()

	# 2. customer buys a VARIANT through the Item Configurator
	ctx = br.new_context(viewport={"width": 1300, "height": 1100})
	page = ctx.new_page()
	bad = []
	page.on("pageerror", lambda e: bad.append(str(e)[:120]))
	page.on("response", lambda r: bad.append(f"{r.status} {r.url[-70:]}") if r.status in (403, 500) else None)
	login(ctx, "shopper@demo.example")
	page.goto(B + "/all-products")
	page.wait_for_timeout(3000)
	page.locator("a[href*='demo-everyday-sneaker']").first.click()
	page.wait_for_timeout(3500)
	page.get_by_role("button", name="Select Variant").click()
	page.wait_for_timeout(1500)
	page.locator(".modal select").nth(0).select_option("42")
	page.wait_for_timeout(600)
	page.locator(".modal select").nth(1).select_option("White")
	page.wait_for_timeout(2200)
	modal = page.locator(".modal.show").inner_text()
	check("Configurator resolves the exact variant", VARIANT in modal, modal[:120])
	check("Configurator price equals the Desk Item Price", f"{price:,.2f}" in modal, (price, modal[:160]))
	page.locator(".modal.show").get_by_role("button", name="Add to Cart").click()
	page.wait_for_timeout(3500)
	page.goto(B + "/cart")
	page.wait_for_timeout(4500)
	cart = page.evaluate("document.querySelector('.cart-container, .page-content, main')?.innerText||''")
	check("Cart shows the variant at the Desk price with a total", VARIANT in cart and f"{price:,.2f}" in cart and "Grand Total" in cart, cart[:200])
	check("Cart offers Place Order (checkout enabled)", "Place Order" in cart)
	page.screenshot(path=f"{OUT}/store-2-cart.png")
	page.get_by_role("button", name="Place Order").click()
	page.wait_for_timeout(6000)
	so_name = page.url.rsplit("/", 1)[-1]
	body = page.evaluate("document.querySelector('.page-content, main')?.innerText||''")
	check("Order confirmation page loads for the customer (no 'Not Permitted')", so_name.startswith("SAL-ORD-") and "Not Permitted" not in body, (page.url, body[:120]))
	check("Order page shows the item and total", VARIANT in body and f"{price:,.2f}" in body, body[:200])
	check("No 'Pay' link for the offline gateway", "Pay Rs" not in body and "Pay " + f"{price:,.2f}" not in body, body[:200])
	page.screenshot(path=f"{OUT}/store-3-order.png")
	check("No server errors during the customer flow", not bad, bad)

	# 3. the order reserved stock at the right warehouse
	so = api(admin, f"/api/resource/Sales Order/{urllib.parse.quote(so_name)}") or {}
	line = (so.get("items") or [{}])[0]
	check("Order line is on the Main warehouse (not the generic 'Stores')", line.get("warehouse") == WAREHOUSE, line.get("warehouse"))
	check("Order rate equals the Desk Item Price", line.get("rate") == price, (line.get("rate"), price))
	actual1, reserved1 = bin_qty(admin)
	check("Placing the order RESERVES stock, no physical change", (actual1, reserved1) == (actual0, reserved0 + 1), (actual1, reserved1))

	# 4. over-ordering is refused
	page.goto(B + "/demo-canvas-tote-bag-1r5hy")
	page.wait_for_timeout(3000)
	page.get_by_role("button", name="Add to Cart").first.click()
	page.wait_for_timeout(3000)
	page.goto(B + "/cart")
	page.wait_for_timeout(4500)
	qty = page.locator("input.cart-qty, input[type=number]").first
	qty.fill("99999")
	qty.press("Tab")
	page.wait_for_timeout(3000)
	page.get_by_role("button", name="Place Order").click()
	page.wait_for_timeout(4500)
	msg = page.evaluate("document.body.innerText")
	check("Ordering more than the stock is refused", "in Stock for item DEMO-TOTE" in msg, msg[-200:])
	ctx.close()

	# 5. Store Owner fulfils in Desk: Delivery Note deducts the physical stock
	oc = br.new_context(viewport={"width": 1440, "height": 1000})
	pg = oc.new_page()
	login(oc, "owner@demo.example")
	pg.goto(B + f"/desk/sales-order/{so_name}")
	pg.wait_for_function("window.cur_frm&&cur_frm.doctype=='Sales Order'", timeout=30000)
	pg.wait_for_timeout(2500)
	create_menu(pg, "Delivery%20Note")
	pg.wait_for_function("window.cur_frm&&cur_frm.doctype=='Delivery Note'", timeout=30000)
	pg.wait_for_timeout(1800)
	pg.evaluate("()=>{cur_frm.savesubmit(); return true}")
	pg.wait_for_timeout(3000)
	btn = pg.locator(".modal.show .btn-primary:visible, .modal.show .btn-modal-primary:visible")
	if btn.count():
		btn.first.click()
	pg.wait_for_timeout(5000)
	dn_name = pg.evaluate("cur_frm.doc.name")
	check("Owner submits the Delivery Note", pg.evaluate("cur_frm.doc.docstatus") == 1, dn_name)
	pg.screenshot(path=f"{OUT}/store-4-delivery.png")
	oc.close()
	actual2, reserved2 = bin_qty(admin)
	check("Delivery DEDUCTS the physical stock and releases the reservation", (actual2, reserved2) == (actual0 - 1, reserved0), (actual2, reserved2))

	# 6. cleanup, newest first; cancelling the Delivery Note puts the stock back
	if not KEEP:
		q = urllib.parse.quote
		cart_quotes = [
			x["name"]
			for x in (api(admin, "/api/resource/Quotation?filters=" + q(json.dumps([["order_type", "=", "Shopping Cart"]])) + "&fields=" + q(json.dumps(["name", "docstatus"]))) or [])
		]
		# ERPNext keeps a cancelled document linked to its reversal ledger entries, so it cannot be
		# deleted: cancelled IS the clean end state (purge: retail_store.demo.purge_cancelled_test_orders)
		for dt, name in (("Delivery Note", dn_name), ("Sales Order", so_name)):
			if name:
				admin.request.post(f"{B}/api/method/frappe.client.cancel", data={"doctype": dt, "name": name})
				state = (api(admin, f"/api/resource/{dt}/{q(name)}") or {}).get("docstatus")
				check(f"cleanup: {dt} {name} cancelled", state == 2, state)
		for name in cart_quotes:
			admin.request.post(f"{B}/api/method/frappe.client.cancel", data={"doctype": "Quotation", "name": name})
		actual3, reserved3 = bin_qty(admin)
		check("cleanup: stock is back where it started", (actual3, reserved3) == (actual0, reserved0), (actual3, reserved3))
	admin.close()
	br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
