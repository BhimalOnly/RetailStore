"""Storefront polish, in a real browser at desktop and phone width:
  * the nav stays pinned to the top while scrolling, translucent with a backdrop blur; an open phone
    menu is solid
  * a discounted product shows a "Sale" badge on its card (and only that product); it goes away with the
    discount. The test creates a temporary Pricing Rule (20% on DEMO-TOTE) and ALWAYS deletes it.
Playwright as in browser_shopper.py:  /tmp/pw/bin/python browser_polish.py   (shots in ./shots/polish/)
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/polish"
os.makedirs(OUT, exist_ok=True)
results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


SALE_TITLES = """[...document.querySelectorAll('.item-card')].filter(c => getComputedStyle(c.querySelector('.card-img-container'), '::after').content.includes('Sale')).map(c => c.querySelector('.product-title').innerText.trim())"""


with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	admin.request.post(B + "/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	settings = admin.request.get(B + "/api/resource/Webshop Settings/Webshop Settings").json()["data"]
	rule = None
	try:
		made = admin.request.post(B + "/api/resource/Pricing Rule", data=json.dumps({
			"title": "ZZ TEST SALE", "apply_on": "Item Code", "items": [{"item_code": "DEMO-TOTE"}], "selling": 1,
			"price_or_product_discount": "Price", "rate_or_discount": "Discount Percentage", "discount_percentage": 20,
			"for_price_list": settings["price_list"], "company": settings["company"],
		}), headers={"Content-Type": "application/json"})
		rule = made.json().get("data", {}).get("name") if made.ok else None
		check("a temporary 20% Pricing Rule on DEMO-TOTE exists", bool(rule), made.text()[:120])

		for label, size in (("desktop", {"width": 1300, "height": 800}), ("390px", {"width": 390, "height": 844})):
			tag = label.replace("px", "")
			page = br.new_page(viewport=size)
			bad = []
			page.on("pageerror", lambda e: bad.append(str(e)[:120]))
			page.goto(B + "/all-products")
			page.wait_for_timeout(3500)
			page.evaluate("window.scrollTo(0, 700)")
			page.wait_for_timeout(500)
			nav = page.evaluate("(() => { const n = document.querySelector('nav.navbar'); const c = getComputedStyle(n); return {top: n.getBoundingClientRect().top, blur: c.backdropFilter || c.webkitBackdropFilter, bg: c.backgroundColor}; })()")
			check(f"{label}: the nav stays at the top of the screen after scrolling", abs(nav["top"]) < 1, nav)
			check(f"{label}: the nav blurs what passes under it", "blur" in (nav["blur"] or ""), nav)
			check(f"{label}: the nav background is translucent", "/" in nav["bg"] or "rgba" in nav["bg"], nav["bg"])
			sale = page.evaluate(SALE_TITLES)
			check(f"{label}: only the discounted product carries the Sale badge", sale == ["DEMO CANVAS TOTE BAG"], sale)
			page.evaluate("window.scrollTo(0, 0)")
			page.screenshot(path=f"{OUT}/cards-{tag}.png")
			page.evaluate("window.scrollTo(0, 700)")
			page.screenshot(path=f"{OUT}/scrolled-{tag}.png")
			check(f"{label}: no horizontal overflow", page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0)
			if size["width"] < 768:
				page.evaluate("window.scrollTo(0, 0)")
				page.click(".navbar-toggler")
				page.wait_for_timeout(700)
				page.evaluate("window.scrollTo(0, 300)")
				page.wait_for_timeout(300)
				bg = page.evaluate("getComputedStyle(document.querySelector('nav.navbar')).backgroundColor")
				check(f"{label}: an open phone menu is solid", "/" not in bg and "rgba" not in bg, bg)
				page.screenshot(path=f"{OUT}/menu-open-{tag}.png")
			check(f"{label}: no uncaught JS errors", not bad, "; ".join(bad[:3]))
			page.close()
	finally:
		if rule:
			gone = admin.request.delete(B + f"/api/resource/Pricing Rule/{rule}")
			check("cleanup: the temporary Pricing Rule is deleted", gone.ok, gone.status)
	page = br.new_page(viewport={"width": 1300, "height": 800})
	page.goto(B + "/all-products")
	page.wait_for_timeout(3500)
	check("without the discount no card carries a Sale badge", page.evaluate(SALE_TITLES) == [])
	br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
