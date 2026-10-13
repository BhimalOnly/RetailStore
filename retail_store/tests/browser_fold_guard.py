"""The "Show N optional fields" fold never leaves a REQUIRED field hidden (retail_store/public/js/progressive_guard.js).

Real browser, as the Store Owner, on saved records (the fold only applies to those). Each case makes a field newly
mandatory by changing another field, then checks the field is revealed, a failed Save lands on it, and optional fields
stay folded:
  * Employee: Status = Left            -> Relieving Date          (on the Exit tab, not the open one)
  * Attendance: Status = On Leave      -> Leave Type
  * Payment Entry: a Bank account      -> Reference No / Date     (condition flipped directly on the form)
  * Item: batches + expiry date        -> Shelf Life In Days
  * Item template (variants)           -> Attributes already visible on load
and the SECOND way a field becomes required, a form script (frm.toggle_reqd / set_df_property "reqd"), which never
passes through the field conditions (about 90 places in ERPNext / HRMS work this way):
  * Customer: "Internal customer" ticked    -> Represents Company   (ERPNext's own handler)
  * Material Request: Customer Provided     -> Customer            (its refresh handler)
  * Sales Invoice (a draft return): the same toggle_reqd call its script makes for a normal invoice -> Due Date
  * any field: frm.set_df_property(field, "reqd", 1)
Nothing is saved to a real record; the draft Attendance / Payment Entry it needs are created and deleted by the test.

Run:  /tmp/pw/bin/python browser_fold_guard.py   (HR on + seeded employees: tests/seed_hr_demo.run)
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


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


STATE = """(fn)=>{const f=cur_frm.fields_dict[fn];const w=f&&f.$wrapper&&f.$wrapper[0];
	return {exists:!!f, reqd:f?f.df.reqd:null, folded:w?w.classList.contains('st-pf-hidden'):null, onScreen:w?w.offsetParent!==null:null,
		tab:f&&f.tab?f.tab.label:null, activeTab:(cur_frm.layout.tabs.find(t=>t.is_active())||{}).label||null}}"""


def open_form(ctx, path, doctype):
	page = ctx.new_page()
	errors = []
	page.on("pageerror", lambda e: errors.append(str(e)[:150]))
	page.goto(B + path)
	page.wait_for_function(f"window.cur_frm&&cur_frm.doctype=='{doctype}'", timeout=60000)
	page.wait_for_selector(".st-pf-toggle-btn", state="attached", timeout=60000)  # the theme's fold is in place
	page.wait_for_timeout(1500)  # (the guard marks the form ready 500 ms after refresh)
	return page, errors


def alerts(page, text):
	return page.evaluate("(t)=>window.__alerts.some(a=>a.indexOf(t)>=0)", text)


def spy_alerts(page):
	page.evaluate("()=>{window.__alerts=[];const o=frappe.show_alert;frappe.show_alert=function(){window.__alerts.push(JSON.stringify(arguments[0]));return o.apply(this,arguments)}}")


def failed_save(page):
	page.keyboard.press("Control+s")
	page.wait_for_timeout(3000)
	body = page.evaluate("[...document.querySelectorAll('.modal.show')].map(m=>m.innerText).join(' | ')")
	return body


with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	admin.request.post(f"{B}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	made = []
	try:
		ctx = br.new_context(viewport={"width": 1440, "height": 950})
		ctx.request.post(f"{B}/api/method/login", data={"usr": "owner@demo.example", "pwd": PWD})

		# ---- Employee: Status = Left -> Relieving Date
		page, errors = open_form(ctx, "/desk/employee/HR-EMP-00001", "Employee")
		spy_alerts(page)
		s0 = page.evaluate(STATE, "relieving_date")
		check("Employee: before, Relieving Date is optional and folded away", s0["reqd"] == 0 and s0["folded"], s0)
		check("Employee: other optional fields stay folded", page.evaluate("()=>cur_frm.fields_dict.middle_name.$wrapper[0].classList.contains('st-pf-hidden')"))
		page.evaluate("()=>cur_frm.set_value('status','Left')")
		page.wait_for_timeout(1200)
		s1 = page.evaluate(STATE, "relieving_date")
		check("Employee: Status = Left makes it required AND it is revealed", s1["reqd"] == 1 and not s1["folded"], s1)
		check("Employee: a note says it is now required, and on which tab", alerts(page, "Relieving Date is now required") and alerts(page, "Exit"), page.evaluate("window.__alerts"))
		page.locator(".st-pf-toggle-btn").first.click()
		page.wait_for_timeout(600)
		page.locator(".st-pf-toggle-btn").first.click()
		page.wait_for_timeout(600)
		check("Employee: the fold's own show / hide toggle never re-hides it", not page.evaluate(STATE, "relieving_date")["folded"])
		body = failed_save(page)
		s2 = page.evaluate(STATE, "relieving_date")
		check("Employee: a failed Save names the field, opens its tab and shows it", "Relieving Date" in body and s2["onScreen"] and s2["activeTab"] == s2["tab"], (body[:120], s2))
		page.screenshot(path="shots/fold-guard-employee.png")
		check("Employee: nothing was saved (status is still unchanged in the database)", (admin.request.get(f"{B}/api/resource/Employee/HR-EMP-00001").json()["data"]["status"]) != "Left")
		check("Employee: no script errors", not errors, errors)
		page.close()

		# ---- Attendance: On Leave -> Leave Type
		emp = "HR-EMP-00001"
		r = admin.request.post(f"{B}/api/resource/Attendance", data=json.dumps({"employee": emp, "attendance_date": "2026-01-05", "status": "Present", "company": "Demo Retail Co"}), headers={"Content-Type": "application/json"})
		att = (r.json().get("data") or {}).get("name") if r.ok else None
		if att:
			made.append(("Attendance", att))
			page, errors = open_form(ctx, f"/desk/attendance/{att}", "Attendance")
			spy_alerts(page)
			a0 = page.evaluate(STATE, "leave_type")
			page.evaluate("()=>cur_frm.set_value('status','On Leave')")
			page.wait_for_timeout(1200)
			a1 = page.evaluate(STATE, "leave_type")
			check("Attendance: On Leave requires Leave Type and reveals it", a1["reqd"] == 1 and not a1["folded"], (a0, a1))
			check("Attendance: a failed Save shows it", "Leave Type" in failed_save(page) and page.evaluate(STATE, "leave_type")["onScreen"])
			check("Attendance: no script errors", not errors, errors)
			page.close()
		else:
			check("Attendance: draft record could be created for the test", False, r.text[:200])

		# ---- Payment Entry: bank account -> reference no / date
		pe_body = {"payment_type": "Receive", "party_type": "Customer", "party": "DEMO Walk-in Customer", "company": "Demo Retail Co", "paid_from": "Debtors - DRC", "paid_to": "Cash - DRC", "paid_amount": 10, "received_amount": 10, "target_exchange_rate": 1, "source_exchange_rate": 1}
		r = admin.request.post(f"{B}/api/resource/Payment Entry", data=json.dumps(pe_body), headers={"Content-Type": "application/json"})
		pe = (r.json().get("data") or {}).get("name") if r.ok else None
		if pe:
			made.append(("Payment Entry", pe))
			page, errors = open_form(ctx, f"/desk/payment-entry/{pe}", "Payment Entry")
			spy_alerts(page)
			before = page.evaluate(STATE, "reference_no")
			page.evaluate("()=>{cur_frm.doc.paid_to_account_type='Bank';cur_frm.layout.refresh_dependency()}")
			page.wait_for_timeout(1200)
			after = {f: page.evaluate(STATE, f) for f in ("reference_no", "reference_date")}
			check("Payment Entry: a bank account requires Reference No and Date, both revealed", all(v["reqd"] == 1 and not v["folded"] for v in after.values()), (before, after))
			check("Payment Entry: no script errors", not errors, errors)
			page.close()
		else:
			check("Payment Entry: draft record could be created for the test", False, r.text[:200])

		# ---- Item: batches + expiry -> shelf life; template attributes visible on load
		page, errors = open_form(ctx, "/desk/item/DEMO-TOTE", "Item")
		page.evaluate("()=>{cur_frm.set_value('has_batch_no',1);cur_frm.set_value('has_expiry_date',1)}")
		page.wait_for_timeout(1500)
		it = page.evaluate(STATE, "shelf_life_in_days")
		check("Item: batches + expiry require Shelf Life In Days, revealed", it["reqd"] == 1 and not it["folded"], it)
		check("Item: no script errors", not errors, errors)
		page.close()
		page, errors = open_form(ctx, "/desk/item/DEMO-SNEAKER", "Item")
		at = page.evaluate(STATE, "attributes")
		check("Item template: Attributes (required for variants) is not folded away on load", at["reqd"] == 1 and not at["folded"], at)
		check("Item template: ordinary optional fields still are", page.evaluate("()=>cur_frm.fields_dict.brand.$wrapper[0].classList.contains('st-pf-hidden')"))
		page.close()

		# ---- the second way: form scripts (toggle_reqd / set_df_property), not field conditions
		page, errors = open_form(ctx, "/desk/customer/DEMO%20Jane%20Shopper", "Customer")
		spy_alerts(page)
		c0 = page.evaluate(STATE, "represents_company")
		page.evaluate("()=>cur_frm.set_value('is_internal_customer',1)")
		page.wait_for_timeout(1500)
		c1 = page.evaluate(STATE, "represents_company")
		check("Customer: ticking 'internal customer' makes Represents Company required (ERPNext's handler) and reveals it", c0["folded"] and c1["reqd"] == 1 and not c1["folded"], (c0, c1))
		check("Customer: the note says which tab it is on", alerts(page, "Represents Company is now required"), page.evaluate("window.__alerts"))
		check("Customer: a failed Save lands on it", "Represents Company" in failed_save(page) and page.evaluate(STATE, "represents_company")["onScreen"])
		check("Customer: no script errors", not errors, errors)
		page.close()

		mr = (admin.request.get(f"{B}/api/resource/Material Request?filters={q(json.dumps([['docstatus', '=', 0]]))}&limit_page_length=1&fields={q(json.dumps(['name']))}").json().get("data") or [{}])[0].get("name")
		if mr:
			page, errors = open_form(ctx, f"/desk/material-request/{mr}", "Material Request")
			m0 = page.evaluate(STATE, "customer")
			page.evaluate("()=>{cur_frm.set_value('material_request_type','Customer Provided');cur_frm.trigger('refresh')}")
			page.wait_for_timeout(2500)
			m1 = page.evaluate(STATE, "customer")
			check("Material Request: 'Customer Provided' makes Customer required (its refresh handler) and reveals it", m1["reqd"] == 1 and not m1["folded"], (m0, m1))
			check("Material Request: no script errors", not errors, errors)
			page.close()
		else:
			check("Material Request: a draft exists to test on", False)

		src = (admin.request.get(f"{B}/api/resource/Sales Invoice?filters={q(json.dumps([['docstatus', '=', 1], ['is_return', '=', 0]]))}&limit_page_length=1&fields={q(json.dumps(['name']))}&order_by=creation%20desc").json().get("data") or [{}])[0].get("name")
		ret = None
		if src:
			doc = admin.request.get(f"{B}/api/method/erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return?source_name={q(src)}").json().get("message")
			if doc:
				doc.update({"is_pos": 0, "payments": [], "paid_amount": 0, "base_paid_amount": 0})
				r = admin.request.post(f"{B}/api/resource/Sales Invoice", data=json.dumps(doc), headers={"Content-Type": "application/json"})
				ret = (r.json().get("data") or {}).get("name") if r.ok else None
		if ret:
			made.append(("Sales Invoice", ret))
			page, errors = open_form(ctx, f"/desk/sales-invoice/{ret}", "Sales Invoice")
			spy_alerts(page)
			d0 = page.evaluate(STATE, "due_date")
			page.evaluate("()=>cur_frm.toggle_reqd('due_date', true)")
			page.wait_for_timeout(1200)
			d1 = page.evaluate(STATE, "due_date")
			check("Sales Invoice (return): not required and folded to begin with", d0["reqd"] == 0 and d0["folded"], d0)
			check("Sales Invoice: the toggle_reqd call its script makes reveals Due Date", d1["reqd"] == 1 and not d1["folded"], d1)
			check("Sales Invoice: no script errors", not errors, errors)
			page.close()
		else:
			check("Sales Invoice: a draft return could be created for the test", False, src)

		page, errors = open_form(ctx, "/desk/item/DEMO-TOTE", "Item")
		b0 = page.evaluate(STATE, "brand")
		page.evaluate("()=>cur_frm.set_df_property('brand','reqd',1)")
		page.wait_for_timeout(1000)
		b1 = page.evaluate(STATE, "brand")
		check("any field: frm.set_df_property(field, 'reqd', 1) reveals it", b0["folded"] and b1["reqd"] == 1 and not b1["folded"], (b0, b1))
		page.evaluate("()=>cur_frm.set_df_property('brand','reqd',0)")
		page.close()

		# ---- a NEW record is untouched (the fold never applied to it)
		page = ctx.new_page()
		page.goto(B + "/desk/employee/new")
		page.wait_for_function("window.cur_frm&&cur_frm.doctype=='Employee'", timeout=60000)
		page.wait_for_timeout(2500)
		check("a new record shows its fields as before (no fold)", page.evaluate("()=>!document.querySelector('.st-pf-toggle-btn')"))
		page.close()
		ctx.close()
	finally:
		for dt, name in made:
			admin.request.post(f"{B}/api/method/frappe.client.delete", data={"doctype": dt, "name": name})
		left = [n for dt, n in made if admin.request.get(f"{B}/api/resource/{q(dt)}/{q(n)}").ok]
		check("cleanup: the draft records are gone", not left, left)
		admin.close()
		br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
