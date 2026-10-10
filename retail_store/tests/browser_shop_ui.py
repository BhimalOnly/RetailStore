"""Variant swatches, quick-view modal and cart drawer, in a real browser at desktop and phone width.

  * product cards: Quick view button (hover on desktop, always visible on touch/phone); colour/size
    swatches only on variant templates, with the REAL values; a swatch opens quick view pre-selected
  * quick view: simple item (price, stock, qty, add) and variant (choose options -> exact variant, its
    price and stock; Add stays disabled until a full combination is chosen; out of stock is shown)
  * Add to cart opens the drawer WITHOUT a page reload; the drawer lists the line, changes quantity,
    removes, shows the subtotal, and closes with Esc / the overlay; the navbar cart icon opens it too
  * a guest who presses Add to cart is sent to the shopper sign-in
  * phone: quick view is a bottom sheet, the drawer is full width, nothing scrolls sideways
Uses the demo shopper; clears the shopper's DRAFT carts before and after. The out-of-stock case points
DEMO-SNEAKER's website warehouse at an empty one and ALWAYS restores it.
Playwright as in browser_shopper.py:  /tmp/pw/bin/python browser_shop_ui.py   (shots in ./shots/shop_ui/)
"""
import json
import os
import shutil
import subprocess
import sys

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/shop_ui"
os.makedirs(OUT, exist_ok=True)
SHOPPER = ("shopper@demo.example", "RetailDemo#2026")
BENCH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def restore_demo_photos():
	"""Saving a Website Item over REST (to empty its warehouse) blanks a website_image that is a plain
	/assets URL, as the demo photos are (webshop only keeps images that are File records). Put them back."""
	if shutil.which("bench"):
		subprocess.run(["bench", "--site", "retail.localhost", "execute", "retail_store.demo.apply_demo_images"], cwd=BENCH, capture_output=True)
		subprocess.run(["bench", "--site", "retail.localhost", "execute", "retail_store.setup.capabilities.backfill_thumbnails"], cwd=BENCH, capture_output=True)


def clear_carts(admin):
	rows = admin.request.get(B + "/api/resource/Quotation", params={"filters": json.dumps([["contact_email", "=", SHOPPER[0]], ["docstatus", "=", 0]]), "fields": '["name"]'}).json().get("data", [])
	for row in rows:
		admin.request.post(B + "/api/method/frappe.client.delete", data={"doctype": "Quotation", "name": row["name"]})


def card(page, title):
	return page.locator(".item-card", has_text=title).first


def overflow(page):
	return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


def line_qty(page, code):
	loc = page.locator(f'.rs-line[data-code="{code}"] .rs-qty-n')
	return loc.inner_text().strip() if loc.count() else None


with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	admin.request.post(B + "/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	clear_carts(admin)
	put_wh = lambda wh: admin.request.put(B + "/api/resource/Website Item/WEB-ITM-0001", data=json.dumps({"website_warehouse": wh}), headers={"Content-Type": "application/json"})
	try:
		for label, size in (("desktop", {"width": 1300, "height": 900}), ("390px", {"width": 390, "height": 844})):
			tag = label.replace("px", "")
			phone = size["width"] < 768
			ctx = br.new_context(viewport=size, has_touch=phone)
			ctx.request.post(B + "/api/method/login", data={"usr": SHOPPER[0], "pwd": SHOPPER[1]})
			page = ctx.new_page()
			bad = []
			page.on("pageerror", lambda e: bad.append(str(e)[:120]))
			page.goto(B + "/all-products")
			page.wait_for_timeout(4500)

			# ---- cards ---------------------------------------------------------------------------
			check(f"{label}: every product card has a Quick view button", page.locator(".item-card").count() == page.locator(".rs-qv-btn").count() > 0)
			rows = page.evaluate("""() => [...document.querySelectorAll('.item-card')].map(c => ({
				name: c.querySelector('.product-title').innerText.trim(),
				vals: [...c.querySelectorAll('.rs-sw')].map(b => b.dataset.val)}))""")
			by = {r["name"].upper(): r["vals"] for r in rows}
			check(f"{label}: the sneaker card shows its real sizes and colours", by.get("DEMO EVERYDAY SNEAKER") == ["40", "41", "42", "Black", "White"] or sorted(by.get("DEMO EVERYDAY SNEAKER", [])) == sorted(["40", "41", "42", "Black", "White"]), by.get("DEMO EVERYDAY SNEAKER"))
			check(f"{label}: the tee card shows its real sizes and colours", sorted(by.get("DEMO COTTON TEE", [])) == sorted(["S", "M", "L", "Black", "Navy"]), by.get("DEMO COTTON TEE"))
			check(f"{label}: plain items (tote, saree) have no swatches", not by.get("DEMO CANVAS TOTE BAG") and not by.get("DEMO WOMEN'S SAREE"))
			white = card(page, "Sneaker").locator(".rs-sw-colour[data-val='White']")
			check(f"{label}: a colour swatch is painted in that colour", white.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(255, 255, 255)")
			btn = card(page, "Tote").locator(".rs-qv-btn")
			if phone:
				check(f"{label}: Quick view is visible without hover", float(btn.evaluate("e => getComputedStyle(e).opacity")) == 1)
			else:
				before = float(btn.evaluate("e => getComputedStyle(e).opacity"))
				card(page, "Tote").hover()
				page.wait_for_timeout(450)
				check(f"{label}: Quick view appears on hover", before == 0 and float(btn.evaluate("e => getComputedStyle(e).opacity")) == 1, before)
			page.screenshot(path=f"{OUT}/grid-{tag}.png")

			# ---- quick view: a plain item, add, drawer, no reload ----------------------------------
			page.evaluate("window.__noReload = 'kept'")
			btn.click()
			page.wait_for_timeout(600)
			qv = page.locator(".rs-qv")
			check(f"{label}: quick view opens as a dialog", qv.is_visible() and qv.get_attribute("role") == "dialog")
			check(f"{label}: ...with name, price and stock", "Canvas Tote" in qv.inner_text() and "Rs 350.00" in qv.inner_text() and "In stock" in qv.inner_text(), qv.inner_text()[:80])
			check(f"{label}: ...and no option pickers for a plain item", page.locator(".rs-qv .rs-opt").count() == 0)
			if phone:
				box = qv.bounding_box()
				check("390px: quick view is a bottom sheet (full width, flush with the bottom)", box["x"] == 0 and box["width"] == size["width"] and abs(box["y"] + box["height"] - size["height"]) < 2, box)
			check(f"{label}: no horizontal overflow with quick view open", overflow(page) <= 0, overflow(page))
			page.screenshot(path=f"{OUT}/quickview-plain-{tag}.png")
			page.click(".rs-qty button[data-d='1']")
			page.click(".rs-add")
			page.wait_for_timeout(3500)
			check(f"{label}: Add to cart closes quick view and opens the cart drawer", not qv.is_visible() and page.locator(".rs-drawer").is_visible())
			check(f"{label}: the page did not reload", page.evaluate("window.__noReload") == "kept" and page.url.endswith("/all-products"), page.url)
			check(f"{label}: the drawer lists the tote at quantity 2", line_qty(page, "DEMO-TOTE") == "2", line_qty(page, "DEMO-TOTE"))
			check(f"{label}: the drawer subtotal is Rs 700.00", page.inner_text(".rs-sub-amt") == "Rs 700.00", page.inner_text(".rs-sub-amt"))
			check(f"{label}: the navbar cart count follows", page.locator("#cart-count").inner_text().strip() == "2", page.locator("#cart-count").inner_text())
			dr = page.locator(".rs-drawer").bounding_box()
			check(f"{label}: the drawer is pinned right ({'full width' if phone else 'up to 420px'})", abs(dr["x"] + dr["width"] - size["width"]) < 2 and (dr["width"] == size["width"] if phone else dr["width"] <= 421), dr)
			check(f"{label}: no horizontal overflow with the drawer open", overflow(page) <= 0, overflow(page))
			page.screenshot(path=f"{OUT}/drawer-{tag}.png")

			# ---- drawer edits ----------------------------------------------------------------------
			page.click('.rs-line[data-code="DEMO-TOTE"] button[aria-label="More"]')
			page.wait_for_timeout(2500)
			check(f"{label}: + raises the quantity and the subtotal", line_qty(page, "DEMO-TOTE") == "3" and page.inner_text(".rs-sub-amt") == "Rs 1,050.00", (line_qty(page, "DEMO-TOTE"), page.inner_text(".rs-sub-amt")))
			page.click('.rs-line[data-code="DEMO-TOTE"] button[aria-label="Fewer"]')
			page.wait_for_timeout(2500)
			check(f"{label}: - lowers it", line_qty(page, "DEMO-TOTE") == "2", line_qty(page, "DEMO-TOTE"))
			page.click('.rs-line[data-code="DEMO-TOTE"] .rs-line-x')
			page.wait_for_timeout(2500)
			check(f"{label}: x removes the line and shows the empty state", "your cart is empty" in page.inner_text(".rs-drawer-items").lower() and not page.locator(".rs-drawer-foot").is_visible())
			page.keyboard.press("Escape")
			page.wait_for_timeout(300)
			check(f"{label}: Esc closes the drawer and unlocks the page", not page.locator(".rs-drawer").is_visible() and not page.evaluate("document.documentElement.classList.contains('rs-lock')"))

			# ---- quick view: a variant -------------------------------------------------------------
			card(page, "Sneaker").locator(".rs-sw-colour[data-val='White']").click()
			page.wait_for_timeout(1500)
			check(f"{label}: a swatch opens quick view with that colour pre-selected", page.locator(".rs-opt[data-attr='DEMO Colour'] .rs-sw.is-on").get_attribute("data-val") == "White")
			check(f"{label}: Add stays disabled until every option is chosen", page.locator(".rs-add").is_disabled() and "select options" in page.inner_text(".rs-add").lower())
			page.click(".rs-opt[data-attr='DEMO Shoe Size'] .rs-sw[data-val='42']")
			page.wait_for_timeout(1800)
			check(f"{label}: White + 42 shows the exact variant's price and stock", "Rs 2,700.00" in page.inner_text(".rs-qv-price") and "In stock" in page.inner_text(".rs-qv-stock"), page.inner_text(".rs-qv-price"))
			check(f"{label}: ...and Add is enabled", not page.locator(".rs-add").is_disabled())
			page.screenshot(path=f"{OUT}/quickview-variant-{tag}.png")
			page.click(".rs-add")
			page.wait_for_timeout(3500)
			check(f"{label}: the drawer holds that exact variant", line_qty(page, "DEMO-SNEAKER-42-WHIT") == "1", line_qty(page, "DEMO-SNEAKER-42-WHIT"))
			page.click('.rs-line[data-code="DEMO-SNEAKER-42-WHIT"] .rs-line-x')
			page.wait_for_timeout(2500)
			if phone:
				page.click(".rs-drawer .rs-x")  # the drawer covers the whole screen: no dimmed area to click
			else:
				page.click(".rs-overlay", position={"x": 5, "y": 5})
			page.wait_for_timeout(300)
			check(f"{label}: " + ("the close button" if phone else "clicking the dimmed page") + " closes the drawer", not page.locator(".rs-drawer").is_visible())
			# Webshop hides the navbar cart icon while the cart is empty, and on a phone it lives in the menu
			card(page, "Tote").locator(".rs-qv-btn").click()
			page.wait_for_timeout(600)
			page.click(".rs-add")
			page.wait_for_timeout(3500)
			page.keyboard.press("Escape")
			page.wait_for_timeout(300)
			if phone:
				page.click(".navbar-toggler")
				page.wait_for_timeout(600)
			page.click("li.shopping-cart a")
			page.wait_for_timeout(1500)
			check(f"{label}: the navbar cart icon opens the drawer (no navigation)", page.locator(".rs-drawer").is_visible() and page.url.endswith("/all-products"), page.url)
			page.click('.rs-line[data-code="DEMO-TOTE"] .rs-line-x')
			page.wait_for_timeout(2500)
			page.keyboard.press("Escape")

			# ---- out of stock variant --------------------------------------------------------------
			if not phone:
				check("out of stock: set up (sneaker's website warehouse emptied)", put_wh("Stores - DRC").ok)
				page.reload()
				page.wait_for_timeout(4500)
				card(page, "Sneaker").locator(".rs-sw-colour[data-val='White']").click()
				page.wait_for_timeout(1200)
				page.click(".rs-opt[data-attr='DEMO Shoe Size'] .rs-sw[data-val='42']")
				page.wait_for_timeout(1800)
				check("out of stock: quick view says so and Add is disabled", "out of stock" in page.inner_text(".rs-qv-stock").lower() and page.locator(".rs-add").is_disabled(), page.inner_text(".rs-qv-stock"))
				page.screenshot(path=f"{OUT}/quickview-out-of-stock-{tag}.png")
				check("out of stock: restored", put_wh("DEMO Main Warehouse - DRC").ok)
				page.keyboard.press("Escape")
				# a PLAIN item (the kurta) with an empty warehouse
				put_kurta = lambda wh: admin.request.put(B + "/api/resource/Website Item/WEB-ITM-0004", data=json.dumps({"website_warehouse": wh}), headers={"Content-Type": "application/json"})
				try:
					put_kurta("Stores - DRC")
					page.reload()
					page.wait_for_timeout(4500)
					card(page, "Kurta").hover()
					card(page, "Kurta").locator(".rs-qv-btn").click()
					page.wait_for_timeout(700)
					check("out of stock: a plain item's quick view says so and Add is disabled", "out of stock" in page.inner_text(".rs-qv-stock").lower() and page.locator(".rs-add").is_disabled(), page.inner_text(".rs-qv-stock"))
				finally:
					put_kurta("DEMO Main Warehouse - DRC")
				page.keyboard.press("Escape")

			check(f"{label}: no uncaught JS errors", not bad, "; ".join(bad[:3]))
			ctx.close()

		# ---- a guest ---------------------------------------------------------------------------------
		guest = br.new_context(viewport={"width": 1300, "height": 900}).new_page()
		guest.goto(B + "/all-products")
		guest.wait_for_timeout(4500)
		card(guest, "Tote").hover()
		card(guest, "Tote").locator(".rs-qv-btn").click()
		guest.wait_for_timeout(600)
		guest.click(".rs-add")
		guest.wait_for_timeout(3500)
		check("guest: Add to cart in quick view goes to the shopper sign-in", "/account/login" in guest.url, guest.url)
	finally:
		put_wh("DEMO Main Warehouse - DRC")
		admin.request.put(B + "/api/resource/Website Item/WEB-ITM-0004", data=json.dumps({"website_warehouse": "DEMO Main Warehouse - DRC"}), headers={"Content-Type": "application/json"})
		clear_carts(admin)
		restore_demo_photos()
	photo = admin.request.get(B + "/api/resource/Website Item/WEB-ITM-0001").json().get("data", {}).get("website_image")
	check("cleanup: the demo photos are back (sneaker has its image)", bool(photo), photo)
	br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
