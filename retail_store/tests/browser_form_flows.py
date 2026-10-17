"""Real forms, real roles: create, save and (where it is submittable) submit a document of each retail doctype through the
actual Desk form, logged in as the demo user who really does that job, with the reviewed form hides in place.

Why: the form review hides hundreds of fields. Field-level tests prove a field is hidden; only saving through the form as that
person proves the document can still be saved when nobody can see the field. The earlier gap: forms were tested as
Administrator, and the POS till was never driven as a floating Cashier+Attendant (see browser_pos_checkout.py for the till).

Each flow reports every dialog / "Missing Fields" / "now required" message it meets. Everything it creates is named RS-UI-FLOW
(or links to such a record) and is recorded in flow_docs.json; remove it with
    bench --site retail.localhost execute retail_store.tests.purge_form_flows.run --kwargs "{'path': '/abs/path/flow_docs.json'}"

Needs Playwright + Chromium (see browser_pos.py), PW_CHROMIUM to override the browser, demo data and the demo users.
Run:  /tmp/pw/bin/python browser_form_flows.py [flow ...]      (no argument = all)
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
PWD = "RetailDemo#2026"
TAG = "RS-UI-FLOW"
RUN = str(int(time.time()))[-6:]
fails = []
created = []  # (doctype, name)
MAIN, DOWNTOWN, AIRPORT = "DEMO Main Warehouse - DRC", "DEMO Store Downtown - DRC", "DEMO Store Airport - DRC"


def check(name, ok, detail=""):
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
	if not ok:
		fails.append(name)


class Session:
	def __init__(self, br, user):
		self.user = user
		self.ctx = br.new_context(viewport={"width": 1400, "height": 950})
		self.ctx.request.post(f"{B}/api/method/login", data={"usr": user, "pwd": PWD})
		self.errors = []

	def new_page(self):
		pg = self.ctx.new_page()
		pg.on("pageerror", lambda e: self.errors.append(str(e)[:160]))
		pg.add_init_script(
			"window.__msgs=[];new MutationObserver(m=>m.forEach(x=>x.addedNodes.forEach(n=>{if(n.nodeType!==1)return;const t=(n.innerText||'').replace(/\\s+/g,' ').trim();"
			"if(t&&/(required|missing|not permitted|no permission|mandatory|invalid|error|cannot|not allowed|insufficient)/i.test(t)&&t.length<400)window.__msgs.push(t)}))).observe(document,{childList:true,subtree:true})"
		)
		return pg

	def close(self):
		self.ctx.close()


def slug(dt):
	return dt.lower().replace(" ", "-")


def open_new(s, dt):
	pg = s.new_page()
	pg.goto(f"{B}/desk/{slug(dt)}/new")
	pg.wait_for_function(f"window.cur_frm && cur_frm.doctype==={json.dumps(dt)} && cur_frm.fields_dict && Object.keys(cur_frm.fields_dict).length>3", timeout=40000)
	pg.wait_for_timeout(900)
	return pg


def open_doc(s, dt, name):
	pg = s.new_page()
	pg.goto(f"{B}/desk/{slug(dt)}/{name}")
	pg.wait_for_function(f"window.cur_frm && cur_frm.doctype==={json.dumps(dt)} && cur_frm.docname==={json.dumps(name)}", timeout=40000)
	pg.wait_for_timeout(900)
	return pg


def setv(pg, field, value, wait=450):
	pg.evaluate("([f,v])=>cur_frm.set_value(f,v)", [field, value])
	pg.wait_for_timeout(wait)


def messages(pg):
	m = pg.evaluate("window.__msgs") or []
	dialogs = pg.evaluate("[...document.querySelectorAll('.modal.show .modal-body, .msgprint')].map(e=>e.innerText.replace(/\\s+/g,' ').trim().slice(0,300)).filter(Boolean)")
	return list(dict.fromkeys(m + dialogs))


def save(pg, label):
	pg.evaluate("void cur_frm.save()")
	try:
		pg.wait_for_function("cur_frm && !cur_frm.is_new() && !cur_frm.is_dirty()", timeout=25000)
		ok = True
	except Exception:
		ok = False
	name = pg.evaluate("cur_frm.docname")
	check(f"{label}: saved", ok, messages(pg)[:3])
	if ok:
		created.append((pg.evaluate("cur_frm.doctype"), name))
	return ok, name


def submit(pg, label):
	pg.evaluate("void cur_frm.savesubmit()")
	ok = False
	for _ in range(6):  # ERPNext may show an informational dialog (a credit note's) before the "Permanently Submit?" confirmation
		pg.wait_for_timeout(1000)
		if pg.evaluate("cur_frm.doc.docstatus===1"):
			ok = True
			break
		pg.evaluate("(()=>{const m=[...document.querySelectorAll('.modal.show')].pop();if(!m)return;const b=m.querySelector('.btn-primary, .btn-modal-primary');if(b)b.click()})()")
	if not ok:
		try:
			pg.wait_for_function("cur_frm.doc.docstatus===1", timeout=15000)
			ok = True
		except Exception:
			ok = False
	check(f"{label}: submitted", ok, messages(pg)[:3])
	return ok


def now_required(pg, label):
	hits = [m for m in (pg.evaluate("window.__msgs") or []) if "now required" in m]
	check(f"{label}: no 'now required' toast", not hits, hits[:2])


def fill_row(pg, table, values, wait=2500):
	"""fill the first, empty row of a child table (a new form starts with one), through the real child-field events"""
	pg.evaluate(
		"([t,v])=>{const f=cur_frm;const first=f.doc[t]&&f.doc[t][0];const key=Object.keys(v)[0];const empty=first&&!first[key];const r=empty?first:f.add_child(t);"
		"let i=0;for(const [k,val] of Object.entries(v)){setTimeout(()=>frappe.model.set_value(r.doctype,r.name,k,val),i*700);i++}}", [table, values]
	)
	pg.wait_for_timeout(len(values) * 700 + wait)


def add_item(pg, item, qty=1, warehouse=None, extra=None):
	"""fill the first (empty) row of the Items grid through the real child-field events"""
	pg.evaluate(
		"([item,qty,wh,extra])=>{const f=cur_frm;const r=(f.doc.items&&f.doc.items[0]&&!f.doc.items[0].item_code)?f.doc.items[0]:f.add_child('items');"
		"frappe.model.set_value(r.doctype,r.name,'item_code',item);}", [item, qty, warehouse, extra or {}]
	)
	pg.wait_for_timeout(3200)
	pg.evaluate(
		"([qty,wh,extra])=>{const r=cur_frm.doc.items[cur_frm.doc.items.length-1];frappe.model.set_value(r.doctype,r.name,'qty',qty);"
		"if(wh){const k=cur_frm.doctype==='Material Request'?'warehouse':(cur_frm.doctype==='Stock Entry'?'s_warehouse':'warehouse');frappe.model.set_value(r.doctype,r.name,k,wh)}"
		"Object.entries(extra).forEach(([k,v])=>frappe.model.set_value(r.doctype,r.name,k,v))}", [qty, warehouse, extra or {}]
	)
	pg.wait_for_timeout(1800)


# ---------------------------------------------------------------- flows ------------------------------------------------------
def flow_item(br):
	s = Session(br, "wh.manager@demo.example")
	pg = open_new(s, "Item")
	code = f"{TAG}-ITEM-{RUN}"
	setv(pg, "item_code", code)
	setv(pg, "item_group", "DEMO Apparel", 800)
	d = pg.evaluate("({name:cur_frm.doc.item_name,uom:cur_frm.doc.stock_uom,stock:cur_frm.doc.is_stock_item})")
	check("Item (Warehouse Manager): name and unit fill themselves", d["name"] == code and d["uom"] == "Nos", d)
	ok, name = save(pg, "Item (Warehouse Manager)")
	now_required(pg, "Item")
	if ok:
		check("Item: reorder levels, taxes and the capability tabs' fields are still on the form", pg.evaluate("['reorder_levels','taxes','safety_stock','min_order_qty'].every(f=>cur_frm.fields_dict[f]&&!cur_frm.fields_dict[f].df.hidden)"))
		setv(pg, "description", "ui flow")  # an edit of the saved record
		check("Item: an existing item can be edited and saved again", save(pg, "Item edit")[0])
	check("Item: no script errors", not s.errors, s.errors[:2])
	s.close()
	return code


def flow_customer(br):
	out = {}
	for usr, label in (("cashier.downtown@demo.example", "pure Cashier"), ("floater@demo.example", "Cashier + Attendant"), ("manager.downtown@demo.example", "Store Manager")):
		s = Session(br, usr)
		pg = open_new(s, "Customer")
		nm = f"{TAG} Customer {label.split()[0]} {RUN}"
		setv(pg, "customer_name", nm)
		d = pg.evaluate("({type:cur_frm.doc.customer_type,grp:cur_frm.doc.customer_group,terr:cur_frm.doc.territory})")
		check(f"Customer ({label}): defaults fill themselves", d["type"] == "Individual" and d["grp"] and d["terr"], d)
		ok, name = save(pg, f"Customer ({label})")
		now_required(pg, f"Customer ({label})")
		if ok and "Store Manager" in label:
			out["customer"] = name
		check(f"Customer ({label}): no script errors", not s.errors, s.errors[:2])
		s.close()
	return out.get("customer")


def flow_item_price(br, item):
	s = Session(br, "manager.downtown@demo.example")
	pg = open_new(s, "Item Price")
	setv(pg, "item_code", item, 1500)
	setv(pg, "price_list", "Standard Selling")
	setv(pg, "price_list_rate", 123)
	d = pg.evaluate("({uom:cur_frm.doc.uom})")
	check("Item Price (Store Manager): the hidden, required UOM fills itself from the item", d["uom"] == "Nos", d)
	save(pg, "Item Price (Store Manager)")
	now_required(pg, "Item Price")
	check("Item Price: no script errors", not s.errors, s.errors[:2])
	s.close()


def flow_sales_order(br, customer):
	s = Session(br, "manager.downtown@demo.example")
	pg = open_new(s, "Sales Order")
	setv(pg, "customer", customer, 3000)
	setv(pg, "delivery_date", pg.evaluate("frappe.datetime.add_days(frappe.datetime.get_today(), 3)"))
	add_item(pg, "DEMO-KURTA-MEN", 1, DOWNTOWN)
	d = pg.evaluate("({cur:cur_frm.doc.currency,pl:cur_frm.doc.selling_price_list,series:cur_frm.doc.naming_series,total:cur_frm.doc.grand_total,taxes:(cur_frm.doc.taxes||[]).length})")
	check("Sales Order (Store Manager): currency, price list, series and totals fill themselves", d["cur"] and d["pl"] and d["series"] and d["total"] > 0, d)
	ok, name = save(pg, "Sales Order (Store Manager)")
	now_required(pg, "Sales Order")
	so = None
	if ok:
		so = name
		submit(pg, "Sales Order (Store Manager)")
	check("Sales Order: no script errors", not s.errors, s.errors[:2])
	s.close()
	return so


def rest_admin(br):
	ctx = br.new_context()
	ctx.request.post(f"{B}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
	return ctx


def bin_of(admin, item, warehouse):
	r = admin.request.get(f"{B}/api/resource/Bin", params={"filters": json.dumps([["item_code", "=", item], ["warehouse", "=", warehouse]]), "fields": json.dumps(["actual_qty", "valuation_rate"])}).json().get("data", [])
	return r[0] if r else {"actual_qty": 0, "valuation_rate": 0}


def flow_sales_invoice(br, customer):
	"""a credit sale made by a manager, then the credit note through the real Return path (is_return is hidden), then the attendant's draft"""
	s = Session(br, "manager.downtown@demo.example")
	pg = open_new(s, "Sales Invoice")
	setv(pg, "customer", customer, 3000)
	setv(pg, "update_stock", 1)
	setv(pg, "due_date", pg.evaluate("frappe.datetime.add_days(frappe.datetime.get_today(), 7)"))
	add_item(pg, "DEMO-KURTA-MEN", 1, DOWNTOWN)
	d = pg.evaluate("({cur:cur_frm.doc.currency,debit:cur_frm.doc.debit_to,pl:cur_frm.doc.selling_price_list,series:cur_frm.doc.naming_series,total:cur_frm.doc.grand_total,taxes:(cur_frm.doc.taxes||[]).length,upd:cur_frm.doc.update_stock})")
	check("Sales Invoice (Store Manager): currency, Debit To, price list and totals fill themselves", d["cur"] and d["debit"] and d["pl"] and d["total"] > 0, d)
	check("Sales Invoice: the 'Update Stock' switch and the VAT table stay on the form", pg.evaluate("['update_stock','taxes','taxes_and_charges','advances'].every(f=>cur_frm.fields_dict[f]&&!cur_frm.fields_dict[f].df.hidden)"))
	ok, name = save(pg, "Sales Invoice (Store Manager)")
	now_required(pg, "Sales Invoice")
	inv = None
	if ok and submit(pg, "Sales Invoice (Store Manager)"):
		inv = name
		# the credit note, exactly as the Create > Return button does it
		pg.evaluate("void frappe.model.open_mapped_doc({method:'erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return', frm: cur_frm})")
		try:
			pg.wait_for_function("cur_frm.doc.is_return===1 && cur_frm.is_new()", timeout=30000)
			pg.wait_for_timeout(1500)
			ok2, rname = save(pg, "Sales Invoice return (credit note)")
			if ok2:
				submit(pg, "Sales Invoice return (credit note)")
		except Exception:
			check("Sales Invoice return: the return form opened", False, messages(pg)[:3])
	check("Sales Invoice: no script errors", not s.errors, s.errors[:2])
	s.close()
	# an attendant+cashier drafts one
	s2 = Session(br, "cashier.mall@demo.example")
	pg2 = open_new(s2, "Sales Invoice")
	setv(pg2, "customer", "DEMO Walk-in Customer", 3000)
	add_item(pg2, "DEMO-TOTE", 1, "DEMO Store Mall - DRC")
	save(pg2, "Sales Invoice draft (Attendant + Cashier)")
	check("Sales Invoice (Attendant + Cashier): no script errors", not s2.errors, s2.errors[:2])
	s2.close()
	return inv


def flow_payment_entry(br, customer):
	"""a customer pays an outstanding invoice: owner makes the invoice, then the payment through the Payment button"""
	s = Session(br, "owner@demo.example")
	pg = open_new(s, "Sales Invoice")
	setv(pg, "customer", customer, 3000)
	setv(pg, "due_date", pg.evaluate("frappe.datetime.add_days(frappe.datetime.get_today(), 7)"))
	add_item(pg, "DEMO-TOTE", 1, DOWNTOWN)
	ok, inv = save(pg, "Sales Invoice for payment (Store Owner)")
	if not (ok and submit(pg, "Sales Invoice for payment (Store Owner)")):
		s.close()
		return
	pg.evaluate("void frappe.call({method:'erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry', args:{dt:'Sales Invoice', dn:cur_frm.docname}, callback:(r)=>{frappe.model.sync(r.message);frappe.set_route('Form','Payment Entry',r.message.name)}})")
	try:
		pg.wait_for_function("cur_frm.doctype==='Payment Entry' && cur_frm.is_new()", timeout=30000)
		pg.wait_for_timeout(1500)
		d = pg.evaluate("({refs:(cur_frm.doc.references||[]).length,paid_from:cur_frm.doc.paid_from,paid_to:cur_frm.doc.paid_to,amount:cur_frm.doc.paid_amount})")
		check("Payment Entry (Store Owner): the payment is allocated to the invoice and the accounts fill themselves", d["refs"] == 1 and d["paid_from"] and d["paid_to"] and d["amount"] > 0, d)
		check("Payment Entry: the allocation table stays on the form", pg.evaluate("cur_frm.fields_dict.references && !cur_frm.fields_dict.references.df.hidden"))
		pg.evaluate("cur_frm.set_value('reference_no','RS-UI-FLOW'); cur_frm.set_value('reference_date', frappe.datetime.get_today())")
		pg.wait_for_timeout(500)
		ok2, pe = save(pg, "Payment Entry (Store Owner)")
		if ok2:
			submit(pg, "Payment Entry (Store Owner)")
		now_required(pg, "Payment Entry")
	except Exception:
		check("Payment Entry: the form opened", False, messages(pg)[:3])
	check("Payment Entry: no script errors", not s.errors, s.errors[:2])
	s.close()


def flow_stock(br):
	admin = rest_admin(br)
	# Stock Entry: a transfer between two stores, by the owner (the app's own in-transit switch is on the form)
	s = Session(br, "owner@demo.example")
	pg = open_new(s, "Stock Entry")
	setv(pg, "stock_entry_type", "Material Transfer", 1500)
	setv(pg, "from_warehouse", DOWNTOWN)
	setv(pg, "to_warehouse", AIRPORT)
	add_item(pg, "DEMO-KURTA-MEN", 1, DOWNTOWN, {"t_warehouse": AIRPORT})
	check("Stock Entry (Store Owner): the In-Transit switch, final destination and barcode scan stay on the form", pg.evaluate("['add_to_transit','rs_final_destination','scan_barcode'].every(f=>cur_frm.fields_dict[f]&&!cur_frm.fields_dict[f].df.hidden)"))
	ok, se = save(pg, "Stock Entry (Store Owner)")
	if ok:
		submit(pg, "Stock Entry (Store Owner)")
	now_required(pg, "Stock Entry")
	check("Stock Entry: no script errors", not s.errors, s.errors[:2])
	# Stock Reconciliation: a count of one item at the quantity already there
	pg = open_new(s, "Stock Reconciliation")
	b = bin_of(admin, "DEMO-TOTE", DOWNTOWN)
	setv(pg, "purpose", "Stock Reconciliation", 800)
	fill_row(pg, "items", {"item_code": "DEMO-TOTE", "warehouse": DOWNTOWN, "qty": b["actual_qty"] + 1, "valuation_rate": b["valuation_rate"] or 100})
	ok, sr = save(pg, "Stock Reconciliation (Store Owner)")
	if ok:
		submit(pg, "Stock Reconciliation (Store Owner)")
	now_required(pg, "Stock Reconciliation")
	check("Stock Reconciliation: the barcode scan stays on the form", pg.evaluate("cur_frm.fields_dict.scan_barcode && !cur_frm.fields_dict.scan_barcode.df.hidden"))
	s.close()


def flow_material_request(br):
	"""a store asks the main warehouse for stock"""
	s = Session(br, "owner@demo.example")
	pg = open_new(s, "Material Request")
	setv(pg, "material_request_type", "Material Transfer", 1200)
	setv(pg, "schedule_date", pg.evaluate("frappe.datetime.add_days(frappe.datetime.get_today(), 5)"))
	setv(pg, "set_warehouse", DOWNTOWN)
	setv(pg, "set_from_warehouse", MAIN)
	fill_row(pg, "items", {"item_code": "DEMO-TOTE", "qty": 2, "schedule_date": pg.evaluate("frappe.datetime.add_days(frappe.datetime.get_today(), 5)")})
	save(pg, "Material Request (Store Owner)")
	now_required(pg, "Material Request")
	check("Material Request: no script errors", not s.errors, s.errors[:2])
	s.close()


def flow_pick_list(br, so):
	if not so:
		return
	s = Session(br, "owner@demo.example")
	pg = open_doc(s, "Sales Order", so)
	pg.evaluate("void frappe.call({method:'erpnext.selling.doctype.sales_order.sales_order.create_pick_list', args:{source_name:cur_frm.docname}, callback:(r)=>{frappe.model.sync(r.message);frappe.set_route('Form','Pick List',r.message.name)}})")
	try:
		pg.wait_for_function("cur_frm.doctype==='Pick List' && cur_frm.is_new()", timeout=30000)
		pg.wait_for_timeout(1500)
		d = pg.evaluate("({locs:(cur_frm.doc.locations||[]).length})")
		check("Pick List (Store Owner): the item locations are there and visible", d["locs"] >= 1 and pg.evaluate("cur_frm.fields_dict.locations && !cur_frm.fields_dict.locations.df.hidden"), d)
		save(pg, "Pick List (Store Owner)")
		now_required(pg, "Pick List")
	except Exception:
		check("Pick List: the form opened from the sales order", False, messages(pg)[:3])
	s.close()


def flow_config(br):
	admin = rest_admin(br)
	company = admin.request.get(f"{B}/api/method/frappe.client.get_value", params={"doctype": "Company", "fieldname": json.dumps(["name", "cost_center", "default_expense_account"]), "filters": json.dumps({})}).json()["message"]
	# Warehouse: a new location
	s = Session(br, "owner@demo.example")
	pg = open_new(s, "Warehouse")
	setv(pg, "warehouse_name", f"{TAG} Location {RUN}")
	ok, wh = save(pg, "Warehouse (Store Owner)")
	now_required(pg, "Warehouse")
	# Loyalty Program: a new programme, configured with the fields that stay visible
	pg = open_new(s, "Loyalty Program")
	check("Loyalty Program: the redemption account, cost centre and auto-enrolment stay on the form", pg.evaluate("['expense_account','cost_center','auto_opt_in'].every(f=>cur_frm.fields_dict[f]&&!cur_frm.fields_dict[f].df.hidden)"))
	acct = admin.request.get(f"{B}/api/resource/Account", params={"filters": json.dumps([["root_type", "=", "Expense"], ["is_group", "=", 0]]), "fields": json.dumps(["name"]), "limit_page_length": 1}).json()["data"][0]["name"]
	setv(pg, "loyalty_program_name", f"{TAG} Rewards {RUN}")
	setv(pg, "from_date", pg.evaluate("frappe.datetime.get_today()"))
	setv(pg, "expense_account", acct)
	setv(pg, "cost_center", company["cost_center"])
	fill_row(pg, "collection_rules", {"tier_name": "Silver", "collection_factor": 10, "min_spent": 0}, 800)
	save(pg, "Loyalty Program (Store Owner)")
	now_required(pg, "Loyalty Program")
	# POS Profile: a new till, duplicated from Downtown's
	pg = open_doc(s, "POS Profile", "DEMO POS Downtown")
	check("POS Profile: the VAT template stays on the form", pg.evaluate("cur_frm.fields_dict.taxes_and_charges && !cur_frm.fields_dict.taxes_and_charges.df.hidden"))
	pg.evaluate("(()=>{const d=frappe.model.copy_doc(cur_frm.doc);d.__newname=%s;frappe.set_route('Form','POS Profile',d.name)})()" % json.dumps(f"{TAG} Till {RUN}"))
	try:
		pg.wait_for_function("cur_frm.doctype==='POS Profile' && cur_frm.is_new()", timeout=20000)
		pg.wait_for_timeout(1200)
		pg.evaluate("cur_frm.doc.applicable_for_users=[]; cur_frm.refresh_field('applicable_for_users')")
		ok, till = save(pg, "POS Profile (Store Owner), a new till copied from Downtown")
		now_required(pg, "POS Profile")
	except Exception:
		check("POS Profile: a copy of an existing till opened", False, messages(pg)[:3])
	# Retail Staff Access: the staff-grants form
	rows = admin.request.get(f"{B}/api/resource/Retail Staff Access", params={"fields": json.dumps(["name"]), "limit_page_length": 1}).json().get("data", [])
	if rows:
		pg = open_doc(s, "Retail Staff Access", rows[0]["name"])
		check("Retail Staff Access: the location restriction, locations and the role editor stay on the form", pg.evaluate("['enabled','locations','roles_html'].every(f=>cur_frm.fields_dict[f]&&!cur_frm.fields_dict[f].df.hidden)"))
	check("config forms: no script errors", not s.errors, s.errors[:2])
	s.close()


ALL = ["item", "customer", "item_price", "sales_order", "sales_invoice", "payment_entry", "stock", "material_request", "pick_list", "config"]


def main():
	want = sys.argv[1:] or ALL
	with sync_playwright() as p:
		exe = os.environ.get("PW_CHROMIUM")
		br = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
		item = flow_item(br) if "item" in want else None
		customer = flow_customer(br) if any(x in want for x in ("customer", "sales_order", "sales_invoice", "payment_entry")) else None
		if "item_price" in want:
			flow_item_price(br, item or "DEMO-TOTE")
		so = None
		if "sales_order" in want or "pick_list" in want:
			so = flow_sales_order(br, customer or "DEMO Walk-in Customer")
		if "sales_invoice" in want:
			flow_sales_invoice(br, customer or "DEMO Walk-in Customer")
		if "payment_entry" in want:
			flow_payment_entry(br, customer or "DEMO Walk-in Customer")
		if "stock" in want:
			flow_stock(br)
		if "material_request" in want:
			flow_material_request(br)
		if "pick_list" in want:
			flow_pick_list(br, so)
		if "config" in want:
			flow_config(br)
		br.close()
	json.dump(created, open("flow_docs.json", "w"))
	print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + '; '.join(fails)}  ({len(created)} documents created: flow_docs.json)")
	sys.exit(1 if fails else 0)


main()
