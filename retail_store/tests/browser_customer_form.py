"""The simplified Customer form (retail_store/setup/forms.py) in a real browser, as the Store Owner.

  * new Customer: starts as Individual; Defaults / Internal Customer / Sales Partner / References are collapsed with their
    labels; the three dead fields are not on the form; "Customer Details" reads Notes; a name alone saves
  * a section that holds data opens by itself after saving (nothing is buried)
  * internal customer: with its section collapsed, a script that makes Represents Company required opens the section and shows
    the field, and a failed Save lands on it (the fold guard + collapsible sections working together)
  * what must stay visible still is (loyalty, tax id, disabled, language, address and contact)
Removes the customer it creates.   Run:  /tmp/pw/bin/python browser_customer_form.py
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
NAME = f"Form Probe {int(time.time())}"
SECTIONS = {"section_break_hwkr": "Defaults", "internal_customer_section": "Internal Customer Accounting", "sales_team_section": "Sales Partner", "references_section": "References"}


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


SECTION = """(fn)=>{const s=cur_frm.layout.sections.find(x=>x.df&&x.df.fieldname===fn);return s?{label:s.df.label,collapsible:!!s.df.collapsible,collapsed:s.is_collapsed()}:null}"""
FIELD = """(fn)=>{const f=cur_frm.fields_dict[fn];if(!f)return null;const w=f.$wrapper&&f.$wrapper[0];return {hiddenDf:!!f.df.hidden,onScreen:!!(w&&w.offsetParent!==null),folded:!!(w&&w.classList.contains('st-pf-hidden')),label:f.df.label,reqd:f.df.reqd}}"""

with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	admin.request.post(f"{B}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	name = None
	try:
		ctx = br.new_context(viewport={"width": 1440, "height": 950})
		ctx.request.post(f"{B}/api/method/login", data={"usr": "owner@demo.example", "pwd": PWD})
		page = ctx.new_page()
		errors = []
		page.on("pageerror", lambda e: errors.append(str(e)[:150]))

		# ---- a new Customer
		page.goto(B + "/desk/customer/new")
		page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Customer'", timeout=60000)
		page.wait_for_timeout(3000)
		check("new Customer: starts as an Individual", page.evaluate("cur_frm.doc.customer_type") == "Individual")
		for fn, label in SECTIONS.items():
			s = page.evaluate(SECTION, fn)
			check(f"new Customer: '{label}' is a collapsed section", s and s["label"] == label and s["collapsible"] and s["collapsed"], s)
		for fn in ("customer_pos_id", "supplier_numbers", "account_manager"):
			f = page.evaluate(FIELD, fn)
			check(f"new Customer: {fn} is not on the form", f and f["hiddenDf"] and not f["onScreen"], f)
		check("new Customer: 'Customer Details' reads Notes", page.evaluate(FIELD, "customer_details")["label"] == "Notes")
		for fn in ("customer_name", "customer_type", "customer_group", "territory"):
			check(f"new Customer: {fn} is on the form", page.evaluate(FIELD, fn)["hiddenDf"] is False)
		page.screenshot(path="shots/customer-form-new.png")
		page.fill('.frappe-control[data-fieldname="customer_name"] input', NAME)
		page.keyboard.press("Tab")
		page.wait_for_timeout(500)
		page.keyboard.press("Control+s")
		saved = True
		try:
			page.wait_for_function("window.cur_frm&&!cur_frm.doc.__islocal&&!String(cur_frm.doc.name).startsWith('new-')", timeout=30000)
		except Exception:
			saved = False
		name = page.evaluate("cur_frm.doc.name") if saved else None
		check("new Customer: a name alone saves", saved and name == NAME, name)
		cust = (admin.request.get(f"{B}/api/resource/Customer/{q(name or 'none')}").json().get("data") or {})
		check("saved: Individual, in a group and territory, enrolled in loyalty", cust.get("customer_type") == "Individual" and cust.get("customer_group") and cust.get("territory") and cust.get("loyalty_program"), {k: cust.get(k) for k in ("customer_type", "customer_group", "territory", "loyalty_program")})

		# ---- a section holding data opens by itself
		page.reload()
		page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Customer'&&!cur_frm.doc.__islocal", timeout=60000)
		page.wait_for_selector(".st-pf-toggle-btn", state="attached", timeout=60000)
		page.wait_for_timeout(2000)
		d0 = page.evaluate(SECTION, "section_break_hwkr")
		check("saved, no defaults set: Defaults is collapsed", d0["collapsed"], d0)
		page.evaluate("()=>cur_frm.set_value('default_price_list','Standard Selling')")
		page.keyboard.press("Control+s")
		page.wait_for_timeout(3500)
		page.reload()
		page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Customer'&&!cur_frm.doc.__islocal", timeout=60000)
		page.wait_for_timeout(3000)
		d1 = page.evaluate(SECTION, "section_break_hwkr")
		check("after saving a default, Defaults opens by itself (nothing is buried)", d1 and not d1["collapsed"], d1)
		page.screenshot(path="shots/customer-form-defaults-open.png")

		# ---- internal customer: the required field inside a collapsed section
		i0 = page.evaluate(SECTION, "internal_customer_section")
		page.evaluate("()=>{window.__alerts=[];const o=frappe.show_alert;frappe.show_alert=function(){window.__alerts.push(JSON.stringify(arguments[0]));return o.apply(this,arguments)}}")
		page.evaluate("()=>cur_frm.set_value('is_internal_customer',1)")
		page.wait_for_timeout(1800)
		i1 = page.evaluate(SECTION, "internal_customer_section")
		f1 = page.evaluate(FIELD, "represents_company")
		check("internal customer: its section was collapsed, and a script making Represents Company required opens it", i0["collapsed"] and not i1["collapsed"] and f1["reqd"] == 1 and not f1["folded"], (i0, i1, f1))
		check("internal customer: the note says it is now required, on the Accounting tab", any("Represents Company is now required" in a and "Accounting" in a for a in page.evaluate("window.__alerts")), page.evaluate("window.__alerts"))
		page.keyboard.press("Control+s")
		page.wait_for_timeout(3000)
		body = page.evaluate("[...document.querySelectorAll('.modal.show')].map(m=>m.innerText).join(' | ')")
		check("internal customer: a failed Save names Represents Company and lands on it", "Represents Company" in body and page.evaluate(FIELD, "represents_company")["onScreen"], body[:200])
		page.screenshot(path="shots/customer-form-internal.png")
		page.keyboard.press("Escape")
		page.evaluate("()=>{cur_frm.set_value('is_internal_customer',0)}")

		# ---- what must stay visible
		for fn in ("loyalty_program", "tax_id", "tax_category", "disabled", "language", "customer_primary_address", "customer_primary_contact", "default_price_list", "credit_limits", "customer_details"):
			f = page.evaluate(FIELD, fn)
			check(f"stays on the form: {fn}", f and f["hiddenDf"] is False, f)
		check("no script errors", not errors, errors)
		ctx.close()
	finally:
		if name:
			for a in (admin.request.get(f"{B}/api/resource/Address?filters={q(json.dumps([['Dynamic Link', 'link_name', '=', name]]))}&limit_page_length=0").json().get("data") or []):
				admin.request.post(f"{B}/api/method/frappe.client.delete", data={"doctype": "Address", "name": a["name"]})
			admin.request.post(f"{B}/api/method/frappe.client.delete", data={"doctype": "Customer", "name": name})
		check("cleanup: the test customer is gone", not admin.request.get(f"{B}/api/resource/Customer/{q(NAME)}").ok)
		admin.close()
		br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
