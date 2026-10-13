"""The simplified Item form (retail_store/setup/forms.py) in a real browser, as the Store Owner.

  * Product Code / Name / Category labels; Item Price's "Price"
  * Deferred Accounting and Customer Details collapsed
  * the Manufacturing / Quality / Purchasing tabs follow the Capabilities toggles (frappe.boot.retail_store_capabilities),
    and always show for a product that already holds data in them (the data-aware escape)
  * one REAL toggle end to end: switch Quality on in Retail Store Settings, reload the form, the tab appears; off, it goes
  * a new product saves through the real form
Removes what it creates and puts the capability back.   Run:  /tmp/pw/bin/python browser_item_form.py
"""
import json
import sys
import time
import urllib.parse

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
PWD = "RetailDemo#2026"
q = urllib.parse.quote
results = []
STAMP = int(time.time())
TEST_ITEM = f"FORMS-BR-{STAMP}"
NEW_ITEM = f"FORMS-NEW-{STAMP}"


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


TABS = "()=>[...document.querySelectorAll('.form-tabs .nav-item')].filter(e=>e.offsetParent!==null).map(e=>e.innerText.trim())"
SECTION = "(fn)=>{const s=cur_frm.layout.sections.find(x=>x.df&&x.df.fieldname===fn);return s?{collapsible:!!s.df.collapsible,collapsed:s.is_collapsed()}:null}"


def open_item(ctx, name):
	page = ctx.new_page()
	page.goto(f"{B}/desk/item/{q(name)}")
	page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Item'&&!cur_frm.doc.__islocal", timeout=60000)
	page.wait_for_timeout(3000)
	return page


def caps_flip(page, **flags):
	"""Change the capability flags the way a reload would, then let Frappe re-read the form's conditions."""
	page.evaluate("(f)=>{Object.assign(frappe.boot.retail_store_capabilities,f);cur_frm.layout.refresh_dependency()}", flags)
	page.wait_for_timeout(500)


with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	admin.request.post(f"{B}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	group = (admin.request.get(f"{B}/api/resource/Item Group?filters={q(json.dumps([['is_group', '=', 0]]))}&limit_page_length=1").json().get("data") or [{}])[0].get("name")
	admin.request.post(f"{B}/api/resource/Item", data=json.dumps({"item_code": TEST_ITEM, "item_group": group, "stock_uom": "Nos"}), headers={"Content-Type": "application/json"})
	quality_before = (admin.request.get(f"{B}/api/resource/Retail Store Settings/Retail Store Settings").json().get("data") or {}).get("enable_quality")
	try:
		ctx = br.new_context(viewport={"width": 1440, "height": 950})
		ctx.request.post(f"{B}/api/method/login", data={"usr": "owner@demo.example", "pwd": PWD})
		errors = []
		page = open_item(ctx, TEST_ITEM)
		page.on("pageerror", lambda e: errors.append(str(e)[:150]))
		caps = page.evaluate("frappe.boot.retail_store_capabilities")
		check("the Capabilities toggles reach the browser", isinstance(caps, dict) and {"manufacturing", "quality", "buying", "ecommerce"} <= set(caps), caps)
		tabs = page.evaluate(TABS)
		page.screenshot(path="shots/item-form-tabs.png")
		want_quality, want_buying = bool(caps["quality"]), bool(caps["buying"])
		want_manufacturing = bool(caps["manufacturing"] or caps["ecommerce"])
		check(f"tabs follow the toggles: Quality {'shown' if want_quality else 'hidden'}", ("Quality" in tabs) == want_quality, tabs)
		check(f"tabs follow the toggles: Purchasing {'shown' if want_buying else 'hidden'}", ("Purchasing" in tabs) == want_buying, tabs)
		check(f"tabs follow the toggles: Manufacturing {'shown' if want_manufacturing else 'hidden'} (it also follows the Online Store)", ("Manufacturing" in tabs) == want_manufacturing, tabs)
		check("the tabs that must always be there are there", all(t in tabs for t in ("Details", "Accounting", "UOM", "Tax", "Inventory", "Sales", "Pricing")), tabs)

		labels = page.evaluate("()=>['item_code','item_name','item_group'].map(f=>cur_frm.fields_dict[f].df.label)")
		check("labels read Product Code / Product Name / Product Category", labels == ["Product Code", "Product Name", "Product Category"], labels)
		for fn in ("deferred_accounting_section", "customer_details"):
			s = page.evaluate(SECTION, fn)
			check(f"{fn} is collapsed", s and s["collapsible"] and s["collapsed"], s)

		# in-page capability flips
		caps_flip(page, quality=0, buying=0, manufacturing=0, ecommerce=0)
		off = page.evaluate(TABS)
		check("all optional capabilities off, no data: Manufacturing, Quality and Purchasing are gone", not any(t in off for t in ("Manufacturing", "Quality", "Purchasing")), off)
		caps_flip(page, quality=1)
		check("Quality on: its tab appears", "Quality" in page.evaluate(TABS))
		caps_flip(page, quality=0, buying=1)
		on = page.evaluate(TABS)
		check("Buying on: Purchasing appears (the product is a purchase item)", "Purchasing" in on and "Quality" not in on, on)
		caps_flip(page, buying=0, manufacturing=1)
		check("Manufacturing on: its tab appears", "Manufacturing" in page.evaluate(TABS))
		caps_flip(page, manufacturing=0)

		# the data-aware escape: a product that already holds data keeps its tab with the capability off
		page.evaluate("()=>{cur_frm.doc.inspection_required_before_delivery=1;cur_frm.layout.refresh_dependency()}")
		page.wait_for_timeout(400)
		check("a product with quality data keeps the Quality tab even with Quality off", "Quality" in page.evaluate(TABS), page.evaluate(TABS))
		page.evaluate("()=>{cur_frm.doc.inspection_required_before_delivery=0;cur_frm.doc.production_capacity=5;cur_frm.layout.refresh_dependency()}")
		page.wait_for_timeout(400)
		check("...and one with manufacturing data keeps the Manufacturing tab", "Manufacturing" in page.evaluate(TABS) and "Quality" not in page.evaluate(TABS), page.evaluate(TABS))
		page.evaluate("()=>{cur_frm.doc.production_capacity=0;cur_frm.layout.refresh_dependency()}")
		check("no script errors on the form", not errors, errors)
		page.close()

		# ---- a variant template keeps its Variants tab and its required Attributes (ERPNext hides that tab for a plain product)
		page = open_item(ctx, "DEMO-SNEAKER")
		check("a variant template still has its Variants tab", "Variants" in page.evaluate(TABS), page.evaluate(TABS))
		check("...with Attributes required and on the form", page.evaluate("()=>({r:cur_frm.fields_dict.attributes.df.reqd,h:!!cur_frm.fields_dict.attributes.df.hidden})") == {"r": 1, "h": False})
		page.close()

		# ---- a REAL toggle: Quality on in Retail Store Settings, reload, the tab shows; off, it goes
		admin.request.put(f"{B}/api/resource/Retail Store Settings/Retail Store Settings", data=json.dumps({"enable_quality": 1}), headers={"Content-Type": "application/json"})
		page = open_item(ctx, TEST_ITEM)
		check("real toggle: Quality switched on in Settings -> the tab is on the Item form after a reload", "Quality" in page.evaluate(TABS), page.evaluate(TABS))
		page.close()
		admin.request.put(f"{B}/api/resource/Retail Store Settings/Retail Store Settings", data=json.dumps({"enable_quality": 1 if quality_before else 0}), headers={"Content-Type": "application/json"})
		page = open_item(ctx, TEST_ITEM)
		check("real toggle: switched back -> the tab is gone again", ("Quality" in page.evaluate(TABS)) == bool(quality_before), page.evaluate(TABS))
		page.close()

		# ---- a new product through the real form
		page = ctx.new_page()
		page.goto(B + "/desk/item/new")
		page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Item'", timeout=60000)
		page.wait_for_timeout(3000)
		page.fill('.frappe-control[data-fieldname="item_code"] input', NEW_ITEM)
		page.keyboard.press("Tab")
		page.evaluate("(g)=>cur_frm.set_value('item_group', g)", group)
		page.wait_for_timeout(1200)
		page.keyboard.press("Control+s")
		saved = True
		try:
			page.wait_for_function("window.cur_frm&&!cur_frm.doc.__islocal&&cur_frm.doc.name", timeout=30000)
		except Exception:
			saved = False
		check("a new product saves through the form (Product Code, Category, Unit)", saved and page.evaluate("cur_frm.doc.name") == NEW_ITEM, page.evaluate("[...document.querySelectorAll('.modal.show')].map(m=>m.innerText).join(' | ')"))
		page.screenshot(path="shots/item-form-new.png")
		page.close()

		# ---- Item Price
		prices = admin.request.get(f"{B}/api/resource/Item Price?limit_page_length=1&fields={q(json.dumps(['name']))}").json().get("data") or []
		if prices:
			page = ctx.new_page()
			page.goto(f"{B}/desk/item-price/{q(prices[0]['name'])}")
			page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Item Price'", timeout=60000)
			page.wait_for_timeout(2500)
			info = page.evaluate("()=>({label:cur_frm.fields_dict.price_list_rate.df.label,others:['item_code','price_list','valid_from','uom'].map(f=>cur_frm.fields_dict[f]&&!cur_frm.fields_dict[f].df.hidden)})")
			check("Item Price: the rate reads Price and every other field is still there", info["label"] == "Price" and all(info["others"]), info)
			page.close()
		ctx.close()
	finally:
		admin.request.put(f"{B}/api/resource/Retail Store Settings/Retail Store Settings", data=json.dumps({"enable_quality": 1 if quality_before else 0}), headers={"Content-Type": "application/json"})
		for name in (TEST_ITEM, NEW_ITEM):
			admin.request.post(f"{B}/api/method/frappe.client.delete", data={"doctype": "Item", "name": name})
		check("cleanup: the test products are gone and Quality is back as it was", not any(admin.request.get(f"{B}/api/resource/Item/{q(n)}").ok for n in (TEST_ITEM, NEW_ITEM)) and (admin.request.get(f"{B}/api/resource/Retail Store Settings/Retail Store Settings").json().get("data") or {}).get("enable_quality") == quality_before)
		admin.close()
		br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
