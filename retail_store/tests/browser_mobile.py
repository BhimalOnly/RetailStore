"""The storefront on a phone (390px), in a real browser: no page scrolls sideways, the cart fits, a
whole checkout works with taps at phone width, and an out-of-stock product page reads correctly
(desktop + phone). Uses the demo shopper (has an address) and DEMO-KURTA-MEN, whose website warehouse is
pointed at an empty warehouse for a moment and ALWAYS restored. Playwright as in browser_shopper.py:
    /tmp/pw/bin/python browser_mobile.py        (screenshots in ./shots/mobile/)
"""
import json
import os
import shutil
import subprocess
import sys

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/mobile"
os.makedirs(OUT, exist_ok=True)
PHONE = {"width": 390, "height": 844}
OOS_ITEM, OOS_ROUTE, MAIN_WH, EMPTY_WH = "WEB-ITM-0004", "demo-indian-wear/demo-mens-kurta-pajama-j8lny", "DEMO Main Warehouse - DRC", "Stores - DRC"
BENCH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def restore_demo_photos():
	"""Saving a Website Item over REST (to empty its warehouse) blanks a website_image that is a plain
	/assets URL, as the demo photos are (webshop keeps only images that are File records). Put them back."""
	if shutil.which("bench"):
		subprocess.run(["bench", "--site", "retail.localhost", "execute", "retail_store.demo.apply_demo_images"], cwd=BENCH, capture_output=True)
		subprocess.run(["bench", "--site", "retail.localhost", "execute", "retail_store.setup.capabilities.backfill_thumbnails"], cwd=BENCH, capture_output=True)


def overflow(page):
	return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	admin.request.post(B + "/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	ctx = br.new_context(viewport=PHONE)
	ctx.request.post(B + "/api/method/login", data={"usr": "shopper@demo.example", "pwd": "RetailDemo#2026"})
	page = ctx.new_page()
	bad = []
	page.on("pageerror", lambda e: bad.append(str(e)[:120]))

	# 1. nothing scrolls sideways at phone width (and at an iPad-portrait 768, where the footer used to)
	for label, path in [("front page", "/"), ("product list", "/all-products"), ("product", "/demo-canvas-tote-bag-1r5hy"), ("shopper login", "/account/login")]:
		page.goto(B + path)
		page.wait_for_timeout(2500)
		check(f"390px: {label} has no horizontal overflow", overflow(page) <= 0, overflow(page))
	page.set_viewport_size({"width": 768, "height": 1000})
	for label, path in [("front page", "/"), ("product", "/demo-canvas-tote-bag-1r5hy")]:
		page.goto(B + path)
		page.wait_for_timeout(2000)
		check(f"768px: {label} has no horizontal overflow", overflow(page) <= 0, overflow(page))
	page.set_viewport_size(PHONE)

	# 2. checkout with taps at phone width
	page.goto(B + "/demo-canvas-tote-bag-1r5hy")
	page.wait_for_timeout(2500)
	page.get_by_role("button", name="Add to Cart").first.click()
	page.wait_for_timeout(3000)
	page.goto(B + "/cart")
	page.wait_for_timeout(4000)
	check("390px: cart has no horizontal overflow", overflow(page) <= 0, overflow(page))
	total = page.locator(".cart-tax-items .item-grand-total.totals").first
	box = total.bounding_box()
	check("390px: the Net Total amount is fully inside the screen", box and box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"], box)
	check("390px: the amount is on one line", "\n" not in total.inner_text().strip(), total.inner_text())
	page.screenshot(path=f"{OUT}/cart-390.png", full_page=True)
	place = page.get_by_role("button", name="Place Order")
	place.scroll_into_view_if_needed()
	pb = place.bounding_box()
	check("390px: Place Order is a full-width, tall-enough tap target", pb and pb["height"] >= 44 and pb["width"] >= 250, pb)
	place.click()
	page.wait_for_timeout(6000)
	so = page.url.rsplit("/", 1)[-1]
	check("390px: Place Order creates the order and shows its page", so.startswith("SAL-ORD-") and "Not Permitted" not in page.inner_text("body"), page.url)
	check("390px: order page has no horizontal overflow", overflow(page) <= 0, overflow(page))
	page.screenshot(path=f"{OUT}/order-390.png", full_page=True)
	if so.startswith("SAL-ORD-"):
		admin.request.post(B + "/api/method/frappe.client.cancel", data={"doctype": "Sales Order", "name": so})
	for q in admin.request.get(B + "/api/resource/Quotation", params={"filters": json.dumps([["contact_email", "=", "shopper@demo.example"], ["docstatus", "=", 0]]), "fields": '["name"]'}).json().get("data", []):
		admin.request.post(B + "/api/method/frappe.client.delete", data={"doctype": "Quotation", "name": q["name"]})

	# 3. out-of-stock product page
	put = lambda wh: admin.request.put(B + f"/api/resource/Website Item/{OOS_ITEM}", data=json.dumps({"website_warehouse": wh}), headers={"Content-Type": "application/json"})
	try:
		check("out of stock: set up (website warehouse emptied)", put(EMPTY_WH).ok)
		for label, size in (("desktop", {"width": 1300, "height": 900}), ("390px", PHONE)):
			page.set_viewport_size(size)
			page.goto(B + "/" + OOS_ROUTE)
			page.wait_for_timeout(3000)
			text = page.inner_text("body")
			check(f"out of stock {label}: product page says Out of stock", "Out of stock" in text)
			check(f"out of stock {label}: no Add to Cart button", page.get_by_role("button", name="Add to Cart").count() == 0)
			check(f"out of stock {label}: no horizontal overflow", overflow(page) <= 0, overflow(page))
			colour = page.eval_on_selector(".out-of-stock", "e => getComputedStyle(e).color")
			check(f"out of stock {label}: the message is dark enough to read", colour == "rgb(179, 38, 30)", colour)
			page.screenshot(path=f"{OUT}/out-of-stock-{label}.png", full_page=True)
		page.goto(B + "/all-products")
		page.wait_for_timeout(3000)
		page.screenshot(path=f"{OUT}/out-of-stock-list-390.png", full_page=True)
	finally:
		check("out of stock: warehouse restored", put(MAIN_WH).ok)
		restore_demo_photos()
	check("no uncaught JS errors", not bad, "; ".join(bad[:3]))
	br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
