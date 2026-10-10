"""Storefront search and filters, in a real browser at desktop and phone width:
  * the Filters panel is populated (category + attributes) and, on a phone, can be opened
  * the suggestion dropdown shows the item's real photo (not Webshop's grey placeholder)
  * pressing Enter in the search box FILTERS the grid (and the term stays in the box / URL)
  * a search with no match shows the styled "No results" state with a way out
  * a category filter narrows the grid; search + filter together work
  * each attribute filter (Colour, Apparel Size, Shoe Size) returns the items whose VARIANTS have it,
    and several together mean one variant with all of them
  * no horizontal overflow at 390px, no JS errors
Playwright as in browser_shopper.py:  /tmp/pw/bin/python browser_search.py   (shots in ./shots/search/)
"""
import os
import sys

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/search"
os.makedirs(OUT, exist_ok=True)
results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def grid_text(page):
	return page.evaluate("(document.querySelector('#products-grid-area')||{innerText:''}).innerText").upper()


def apply_filters(page, phone, *labels):
	"""Fresh listing, open the panel on a phone, tick each label, wait for the grid to refresh."""
	page.goto(B + "/all-products")
	page.wait_for_timeout(3500)
	if phone:
		page.click(".rs-filter-toggle")
	for label in labels:
		page.locator(f'#product-filters input[data-attribute-value="{label}"]').first.click()
		page.wait_for_timeout(3000)
	return grid_text(page)


with sync_playwright() as p:
	br = p.chromium.launch()
	for label, size in (("desktop", {"width": 1300, "height": 900}), ("390px", {"width": 390, "height": 844})):
		page = br.new_page(viewport=size)
		bad = []
		page.on("pageerror", lambda e: bad.append(str(e)[:120]))
		tag = label.replace("px", "")
		phone = size["width"] < 768

		page.goto(B + "/all-products")
		page.wait_for_timeout(3500)
		check(f"{label}: all demo products listed to start with", all(w in grid_text(page) for w in ("SNEAKER", "KURTA", "SAREE")))
		if phone:
			check(f"{label}: Filters panel is collapsed with a Filters button", page.locator(".rs-filter-toggle").count() == 1 and not page.evaluate("!!document.querySelector('#product-filters').offsetParent"))
			page.click(".rs-filter-toggle")
			page.wait_for_timeout(700)
		panel = page.inner_text("#product-filters")
		check(f"{label}: Filters panel offers categories", "DEMO Apparel" in panel and "DEMO Footwear" in panel, panel[:80])
		check(f"{label}: Filters panel offers attributes (colour, size)", "Navy" in panel and "42" in panel)
		page.screenshot(path=f"{OUT}/filters-{tag}.png")
		if phone:
			page.click(".rs-filter-toggle")

		page.fill("#search-box", "tote")
		page.wait_for_timeout(2500)
		srcs = page.evaluate("[...document.querySelectorAll('#search-results-container img.item-thumb')].map(i => i.getAttribute('src'))")
		check(f"{label}: suggestion shows the item's own photo", srcs and all("demo/tote" in s for s in srcs), srcs)
		page.screenshot(path=f"{OUT}/suggest-{tag}.png")

		page.fill("#search-box", "kurta")
		page.press("#search-box", "Enter")
		page.wait_for_timeout(4000)
		text = grid_text(page)
		check(f"{label}: Enter filters the grid to the match", "KURTA" in text and "SNEAKER" not in text and "SAREE" not in text, text[:80])
		check(f"{label}: the search term is in the URL and still in the box", "search=kurta" in page.url and page.input_value("#search-box") == "kurta", page.url)
		page.screenshot(path=f"{OUT}/results-{tag}.png", full_page=True)

		page.goto(B + "/all-products?search=zzzzqq")
		page.wait_for_timeout(4000)
		nr = page.locator(".rs-noresults")
		check(f"{label}: a search with no match shows the No results state", nr.count() == 1 and "zzzzqq" in nr.inner_text() and "No results" in nr.inner_text())
		check(f"{label}: ...with a way out (Clear search / Browse all products)", nr.locator("a").count() == 2)
		check(f"{label}: ...and no products listed", "ADD TO CART" not in page.inner_text("body").upper())
		page.screenshot(path=f"{OUT}/no-results-{tag}.png", full_page=True)
		nr.locator("a").first.click()
		page.wait_for_timeout(3500)
		check(f"{label}: Clear search brings every product back", "SNEAKER" in grid_text(page) and "search=" not in page.url, page.url)

		# a category filter narrows the grid; with a search on top it still works
		page.goto(B + "/all-products")
		page.wait_for_timeout(3500)
		if phone:
			page.click(".rs-filter-toggle")
		page.locator("#product-filters label:has-text('DEMO Indian Wear')").first.click()
		page.wait_for_timeout(3500)
		text = grid_text(page)
		check(f"{label}: category filter narrows the grid", "KURTA" in text and "SAREE" in text and "SNEAKER" not in text and "TOTE" not in text, text[:80])
		page.goto(B + "/all-products?search=saree&field_filters=%7B%22item_group%22%3A%5B%22DEMO+Indian+Wear%22%5D%7D")
		page.wait_for_timeout(4000)
		text = grid_text(page)
		check(f"{label}: search + category filter together", "SAREE" in text and "KURTA" not in text, text[:80])
		# attribute filters resolve through the variants (templates are published, variants are not)
		for labels, want, unwanted in (
			(("Navy",), ("TEE",), ("SNEAKER", "TOTE", "SAREE")),
			(("Black",), ("TEE", "SNEAKER"), ("TOTE", "SAREE")),
			(("42",), ("SNEAKER",), ("TEE", "TOTE")),
			(("M",), ("TEE",), ("SNEAKER", "TOTE")),
			(("White", "42"), ("SNEAKER",), ("TEE",)),
		):
			text = apply_filters(page, phone, *labels)
			check(f"{label}: attribute filter {' + '.join(labels)}", all(w in text for w in want) and not any(u in text for u in unwanted), text[:90])
		page.screenshot(path=f"{OUT}/attribute-filter-{tag}.png", full_page=True)
		text = apply_filters(page, phone, "White", "S")
		check(f"{label}: attributes no single variant has -> nothing listed", "ADD TO CART" not in page.inner_text("body").upper() and page.locator(".rs-noresults").count() == 1, text[:60])
		for path in ("/all-products", "/all-products?search=zzzzqq"):
			page.goto(B + path)
			page.wait_for_timeout(3500)
			check(f"{label}: {path} has no horizontal overflow", page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0)
		check(f"{label}: no uncaught JS errors", not bad, "; ".join(bad[:3]))
		page.close()
	br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
