"""Browser click-through of the storefront polish batch and the staff-side wording/credit changes.

Run:  /path/to/pw/bin/python browser_storefront_batch.py   (needs the DEMO shopper and one demo order)
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
	if user:
		assert ctx.request.post(f"{B}/api/method/login", data={"usr": user, "pwd": PWD}).status == 200
	return ctx, page


with sync_playwright() as p:
	br = p.chromium.launch()

	# --- guest: home page, nav, footer, empty cart
	ctx, page = login(br, None)
	page.goto(B + "/")
	page.wait_for_selector(".rs-hero", timeout=60000)
	check("hero shows product pictures on the right", page.locator(".rs-hero-art img").count() >= 2)
	nav = page.inner_text("nav.navbar").lower()
	check("top bar has Categories and New arrivals", "categories" in nav and "new arrivals" in nav, nav)
	foot = page.inner_text("footer.web-footer")
	check("footer has shop links", all(w in foot for w in ("Shop all", "Cart", "My orders")), foot)
	check("no Solvronix/ERPNext/Frappe credit on the public site", not any(w in page.content() for w in ("Powered by Solvronix", "Powered by ERPNext", "Powered by Frappe")))
	page.click("text=New arrivals >> nth=0")
	page.wait_for_timeout(800)
	check("New arrivals link scrolls to that section", page.evaluate("document.getElementById('new-arrivals').getBoundingClientRect().top < 400"))
	page.goto(B + "/cart")
	page.wait_for_selector(".cart-empty-message", timeout=30000)
	page.wait_for_timeout(800)
	cart = page.inner_text(".cart-empty").lower()
	check("guest cart: new wording, no 'See past orders'", "your cart is empty" in cart and "start shopping" in cart and "past orders" not in cart, cart)
	page.click(".cart-empty >> text=Start shopping")
	page.wait_for_url("**/all-products", timeout=20000)
	check("Start shopping goes to the products", True)

	# --- shopper: order page, lists, account pages
	ctx, page = login(br, "shopper@demo.example")
	page.goto(B + "/orders")
	page.wait_for_selector(".list-item-status, .indicator-pill", timeout=30000)
	page.wait_for_timeout(800)
	side = page.inner_text("body")
	check("sidebar: no Quotations/Invoices/Shipments", not any(w in side for w in ("Quotations", "Invoices", "Shipments")))
	check("sidebar: Receipts and Deliveries instead", "Receipts" in side and "Deliveries" in side)
	check("orders list shows shop status words", "To Deliver" not in side and ("Order received" in side or "Completed" in side), side[:300])
	href = page.evaluate("()=>{const a=[...document.querySelectorAll('a')].find(x=>/\\/orders\\/SAL/.test(x.href));return a&&a.href}")
	page.goto(href)
	page.wait_for_selector(".rs-order-status", timeout=30000)
	page.wait_for_timeout(800)
	body = page.inner_text("body")
	check("order page line shows a product name, not a code", "DEMO-" not in body.split("Grand Total")[0].split("Item")[-1], body[:400])
	check("order page names the variant options", "(" in body and "DEMO Everyday" in body)
	gt = page.locator(".order-taxes").first.bounding_box()
	check("Grand Total sits on one line", gt and gt["height"] < 40, gt)
	page.screenshot(path=f"{OUT}/sf-order-final.png")
	page.goto(B + "/addresses")
	page.wait_for_timeout(2500)
	check("addresses empty state is friendly", "Nothing to show" not in page.inner_text("body"))
	page.goto(B + "/me")
	page.wait_for_selector("text=Edit Profile", timeout=30000)
	page.wait_for_timeout(800)
	me = page.inner_text("body")
	check("/me hides third-party apps and Portal", "3rd party" not in me and "Portal" not in me, me)

	# --- staff: credit and home layout
	ctx, page = login(br, "cashier.downtown@demo.example")
	page.goto(B + "/desk/retail-store")
	page.wait_for_selector(".ce-block", timeout=60000)
	page.wait_for_timeout(2500)
	check("cashier does not see 'Powered by Solvronix'", not page.locator("#st-powered-by:visible").count())
	blocks = page.evaluate("()=>document.querySelectorAll('.ce-block').length")
	check("cashier home: only the blocks they can use are laid out (no holes)", blocks <= 7, blocks)
	body = page.inner_text("body")
	check("cashier home does not offer Retail Store Settings / Staff Access", "Retail Store Settings" not in body and "Retail Staff Access" not in body)
	ctx, page = login(br, "wh.attendant@demo.example")
	page.goto(B + "/desk/retail-store")
	page.wait_for_selector(".ce-block", timeout=60000)
	page.wait_for_timeout(2000)
	check("attendant home: no setup shortcuts", "Retail Store Settings" not in page.inner_text("body"))
	ctx, page = login(br, "owner@demo.example")
	page.goto(B + "/desk/retail-store")
	page.wait_for_selector(".ce-block", timeout=60000)
	page.wait_for_timeout(2000)
	check("owner home still has Retail Store Settings", "Retail Store Settings" in page.inner_text("body"))
	check("owner does not see 'Powered by Solvronix'", not page.locator("#st-powered-by:visible").count())
	print("\nFAILURES:", fails or "none")
