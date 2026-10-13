"""POS "New Customer" quick entry in a real browser, as the Downtown cashier, light and dark:

  * the two opt-in boxes are UNTICKED every time the dialog opens (and after ticking one, cancelling, reopening),
    with the real input, the hidden duplicate and the rendered state all checked
  * a retail customer defaults to Individual, Country starts as the company's (Mauritius)
  * a missing City is reported, then fixed and saved: the customer and its address exist, consent stays off
  * Edit Full Form hands over the real field names: the full Customer form saves with its address
  * Mauritian Rupee can be found in the currency picker

Needs Playwright and an open POS shift (tests/pos_shift_setup.ensure_open). Removes what it creates.
Run:  /tmp/pw/bin/python browser_customer_quick_entry.py
"""
import json
import os
import sys
import time
import urllib.parse

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/quick-entry"
PWD = "RetailDemo#2026"
os.makedirs(OUT, exist_ok=True)
results = []
q = urllib.parse.quote
STAMP = int(time.time())


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def login(ctx, user, pwd=PWD):
	ctx.request.post(f"{B}/api/method/login", data={"usr": user, "pwd": pwd})


def api(ctx, path):
	r = ctx.request.get(f"{B}{path}")
	return r.json().get("data") if r.ok else None


PROBE = """()=>['custom_whatsapp_optin','custom_sms_optin'].map(f=>{
	const ctl=document.querySelector('.modal.show .frappe-control[data-fieldname='+f+']');
	const real=ctl.querySelector('input[data-fieldname='+f+']'), dummy=ctl.querySelector('input.disabled-deselected');
	const box=real.getBoundingClientRect();
	return {real:real.checked, doc:cur_dialog.doc[f]||0, shown:box.width>0, dummyHidden:!dummy||getComputedStyle(dummy.parentElement).display==='none'||dummy.getBoundingClientRect().width===0,
		look:getComputedStyle(real).backgroundColor}})"""


def open_dialog(page, name):
	if page.locator(".reset-customer-btn:visible").count():  # a customer is selected: go back to the search box
		page.locator(".reset-customer-btn").first.click()
		page.wait_for_timeout(1200)
	page.locator(".customer-section input:visible, .customer-cart-container input:visible").first.fill(name)
	page.wait_for_timeout(2200)
	page.get_by_text("Create a new Customer", exact=False).first.click()
	page.wait_for_selector(".modal.show", timeout=30000)
	page.wait_for_timeout(2500)


def type_into(page, field, value):
	page.click(f'.modal.show input[data-fieldname="{field}"]')
	page.keyboard.type(value)
	page.keyboard.press("Tab")
	page.wait_for_timeout(300)


def open_pos(br, theme):
	ctx = br.new_context(viewport={"width": 1440, "height": 950})
	page = ctx.new_page()
	login(ctx, "cashier.downtown@demo.example")
	page.goto(B + "/desk/point-of-sale")
	page.wait_for_selector(".rs-pos-back, .rs-stale-dialog", timeout=90000)
	page.wait_for_timeout(3500)
	page.evaluate(f"document.documentElement.setAttribute('data-theme','{theme}')")
	return ctx, page


def addresses_of(ctx, customer):
	f = q(json.dumps([["Dynamic Link", "link_doctype", "=", "Customer"], ["Dynamic Link", "link_name", "=", customer]]))
	return api(ctx, f"/api/resource/Address?filters={f}&fields={q(json.dumps(['name', 'city', 'country', 'address_line1']))}&limit_page_length=0") or []


made = []
with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	login(admin, "Administrator", "admin")
	try:
		# ---- defaults, both themes
		for theme in ("light", "dark"):
			ctx, page = open_pos(br, theme)
			open_dialog(page, f"Qe Probe {theme} {STAMP}")
			s = page.evaluate(PROBE)
			check(f"{theme}: both opt-in boxes are unticked when the dialog opens", all(not x["real"] and not x["doc"] for x in s), s)
			check(f"{theme}: the hidden duplicate checkbox cannot show a tick", all(x["dummyHidden"] for x in s), s)
			check(f"{theme}: the two boxes are really on screen", all(x["shown"] for x in s), s)
			check(f"{theme}: 'Only tick if the customer said yes.' is shown", "Only tick if the customer said yes" in page.locator(".modal.show").inner_text())
			check(f"{theme}: Customer Type starts as Individual", page.evaluate("cur_dialog.get_value('customer_type')") == "Individual")
			check(f"{theme}: Country starts as Mauritius", page.evaluate("cur_dialog.get_value('country_address')") == "Mauritius", page.evaluate("cur_dialog.get_value('country_address')"))
			check(f"{theme}: first / last name stay hidden for an Individual", not page.locator('.modal.show [data-fieldname="map_to_first_name"]:visible').count())
			page.screenshot(path=f"{OUT}/quick-entry-{theme}-open.png", clip={"x": 430, "y": 40, "width": 590, "height": 520})
			page.locator('.modal.show input[data-fieldname="custom_whatsapp_optin"]').check()
			page.wait_for_timeout(300)
			ticked = page.evaluate(PROBE)[0]["real"]
			check(f"{theme}: ticking works (so the unticked reading above means something)", ticked)
			page.keyboard.press("Escape")
			page.wait_for_timeout(1200)
			open_dialog(page, f"Qe Probe {theme} again {STAMP}")
			s = page.evaluate(PROBE)
			check(f"{theme}: reopened after ticking + cancelling: unticked again", all(not x["real"] for x in s), s)
			ctx.close()

		# ---- flow 1: a missing City is reported, then fixed; Save creates customer + address
		ctx, page = open_pos(br, "light")
		name1 = f"Qe Flow Save {STAMP}"
		made.append(name1)
		open_dialog(page, name1)
		type_into(page, "address_line1", "12 Test Street")
		page.locator('.modal.show .btn-primary:visible, .modal.show .btn-modal-primary:visible').first.click()
		page.wait_for_timeout(2500)
		msg = page.evaluate("[...document.querySelectorAll('.modal.show')].map(m=>m.innerText).join(' | ')")
		check("address line without a city: the missing City is named", "City" in msg, msg[:200])
		page.screenshot(path=f"{OUT}/quick-entry-missing-city.png")
		page.locator(".modal.show .btn-modal-close:visible").last.click()  # only the message on top (Escape would close both)
		page.wait_for_timeout(900)
		check("the message closes and the quick-entry dialog is still there", page.locator('.modal.show input[data-fieldname="city"]:visible').count() == 1)
		type_into(page, "city", "Port Louis")
		check("after the error, the dialog kept what was typed", page.evaluate("cur_dialog.get_value('address_line1')") == "12 Test Street" and page.evaluate("cur_dialog.get_value('country_address')") == "Mauritius")
		page.locator('.modal.show .btn-primary:visible, .modal.show .btn-modal-primary:visible').first.click()
		page.wait_for_timeout(5000)
		check("Save: the dialog closes and the customer is on the sale", page.locator(".modal.show").count() == 0 and name1 in page.evaluate("document.querySelector('.customer-section')?.innerText||''"))
		c1 = api(admin, f"/api/resource/Customer/{q(name1)}") or {}
		check("Save: customer is an Individual with consent OFF and no consent stamps", c1.get("customer_type") == "Individual" and not c1.get("custom_whatsapp_optin") and not c1.get("custom_sms_optin") and not c1.get("custom_whatsapp_optin_on"), {k: v for k, v in c1.items() if "optin" in k or k == "customer_type"})
		a1 = (addresses_of(admin, name1) or [{}])[0]
		check("Save: its address has the city and Country Mauritius", a1.get("city") == "Port Louis" and a1.get("country") == "Mauritius", a1)
		ctx.close()

		# ---- flow 2: Edit Full Form keeps the address, and the full form saves
		ctx, page = open_pos(br, "light")
		name2 = f"Qe Flow Full {STAMP}"
		made.append(name2)
		open_dialog(page, name2)
		type_into(page, "address_line1", "34 Other Road")
		type_into(page, "city", "Curepipe")
		page.get_by_text("Edit Full Form").first.click()
		page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Customer'", timeout=60000)
		page.wait_for_timeout(2500)
		check("Edit Full Form: the full form received the real country field", page.evaluate("cur_frm.doc.country") == "Mauritius" and page.evaluate("cur_frm.doc.city") == "Curepipe", page.evaluate("({country:cur_frm.doc.country,city:cur_frm.doc.city,alias:cur_frm.doc.country_address})"))
		page.keyboard.press("Control+s")
		saved = True
		try:  # the name is read the moment the save lands: Frappe then routes back to the sale
			name2 = page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Customer'&&!cur_frm.doc.__islocal&&!String(cur_frm.doc.name).startsWith('new-')&&cur_frm.doc.name", timeout=30000).json_value()
			made[-1] = name2
		except Exception:
			saved = False
		page.wait_for_timeout(1500)
		body = page.evaluate("[...document.querySelectorAll('.modal.show')].map(m=>m.innerText).join(' | ')")
		check("Edit Full Form: Save works, no 'Missing Values Required: Country'", saved and "Missing Values" not in body, body[:200])
		page.screenshot(path=f"{OUT}/quick-entry-full-form-saved.png")
		c2 = api(admin, f"/api/resource/Customer/{q(name2)}") or {}
		a2 = (addresses_of(admin, name2) or [{}])[0]
		check("Edit Full Form: the address was created with Country Mauritius", a2.get("country") == "Mauritius" and a2.get("city") == "Curepipe", (name2, a2))
		check("Edit Full Form: consent stays OFF", not c2.get("custom_whatsapp_optin") and not c2.get("custom_sms_optin"), c2.get("custom_whatsapp_optin"))
		ctx.close()

		# ---- the Mauritian Rupee can be found
		cur = api(admin, "/api/resource/Currency?filters=" + q(json.dumps([["name", "=", "MUR"]])) + "&fields=" + q(json.dumps(["name", "enabled"])))
		check("Mauritian Rupee (MUR) is enabled", cur and cur[0]["enabled"] == 1, cur)
		oc = br.new_context(viewport={"width": 1440, "height": 900})
		og = oc.new_page()
		login(oc, "owner@demo.example")
		og.goto(B + "/desk/customer")
		og.wait_for_selector(".page-head", timeout=60000)
		og.wait_for_timeout(3000)
		found = og.evaluate("""async()=>{const r=await frappe.call({method:'frappe.desk.search.search_link',args:{doctype:'Currency',txt:'MUR'}});return (r.message||r.results||[]).map(x=>x.value)}""")
		check("'Select Currency' search for MUR now finds it", "MUR" in found, found)
		oc.close()
	finally:
		for name in made:
			for a in addresses_of(admin, name):
				admin.request.post(f"{B}/api/method/frappe.client.delete", data={"doctype": "Address", "name": a["name"]})
			admin.request.post(f"{B}/api/method/frappe.client.delete", data={"doctype": "Customer", "name": name})
		left = [n for n in made if api(admin, f"/api/resource/Customer/{q(n)}")]
		check("cleanup: the test customers are gone", not left, left)
		admin.close()
		br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
