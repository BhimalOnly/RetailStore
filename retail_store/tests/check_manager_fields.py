"""Manager-only fields (permlevel 1): payment terms on Customer / Sales Order / Sales Invoice / POS Invoice, and the
POS Profile till policies (allow discount / rate change, ignore pricing rule, validate stock on save).

Run:  bench --site retail.localhost execute retail_store.tests.check_manager_fields.run
Everything runs in one transaction that is rolled back. Proves: a manager can set the terms, a cashier still SEES them
but cannot change them, and an invoice made at the till for a credit customer keeps the customer's terms. The POS Profile
toggles are managers-only (the till roles do not even see them), yet the till still honours them."""
import frappe
from frappe.utils import add_days, today

from retail_store.setup import roles

results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


POLICY = ("allow_discount_change", "allow_rate_change", "ignore_pricing_rule", "validate_stock_on_save")


def run():
	manager, cashier = "manager.downtown@demo.example", "cashier.downtown@demo.example"
	try:
		frappe.set_user("Administrator")
		for dt in roles.LEVEL1_DOCTYPES:
			rows = {(r.role): r for r in frappe.get_all("Custom DocPerm", filters={"parent": dt, "permlevel": 1}, fields=["role", "read", "write"])}
			check(f"{dt}: Store Manager / Owner / Admin can read and write at level 1", all(rows.get(r) and rows[r].read and rows[r].write for r in roles.LEVEL1_WRITERS))
		check("Sales Invoice / POS Invoice: Frappe's own 'All' read at level 1 is left alone", all(frappe.db.exists("Custom DocPerm", {"parent": dt, "role": "All", "permlevel": 1, "read": 1, "write": 0}) for dt in ("Sales Invoice", "POS Invoice")))
		check("Customer: the till roles can still read level 1", all(frappe.db.exists("Custom DocPerm", {"parent": "Customer", "role": r, "permlevel": 1, "read": 1}) for r in ("Store Cashier", "Store Attendant")))

		# ---- POS Profile till policies: managers only, and the till still honours them -------------------------------
		rows = {r.role: r for r in frappe.get_all("Custom DocPerm", filters={"parent": "POS Profile", "permlevel": 1}, fields=["role", "read", "write"])}
		check("POS Profile level 1: only Store Manager / Owner / Admin, nobody else", set(rows) == set(roles.LEVEL1_WRITERS), sorted(rows))
		pos_meta = frappe.get_meta("POS Profile")
		check("POS Profile: all four fields are permlevel 1 and not hidden", all(pos_meta.get_field(f).permlevel == 1 and not pos_meta.get_field(f).hidden for f in POLICY))
		from frappe.client import get as client_get

		profile = "DEMO POS Downtown"  # users are store-scoped: both test users work at Downtown
		for f in POLICY:
			frappe.db.set_value("POS Profile", profile, f, 0)
		frappe.set_user(manager)
		d = frappe.get_doc("POS Profile", profile)
		# a field the user may not read is not removed from the document: Frappe sets its value to None
		seen_by_manager = client_get("POS Profile", profile)
		check("manager SEES the four till policies", all(seen_by_manager.get(f) is not None for f in POLICY), {f: seen_by_manager.get(f) for f in POLICY})
		d.allow_discount_change, d.allow_rate_change, d.ignore_pricing_rule, d.validate_stock_on_save = 1, 1, 1, 1
		d.save()
		check("manager can change all four", all(frappe.db.get_value("POS Profile", profile, f) == 1 for f in POLICY))
		frappe.set_user(cashier)
		seen = client_get("POS Profile", profile)
		# the real values are 1 (a manager just set them): a cashier gets None / 0 back, never the setting
		check("cashier does NOT see the four till policies (values are withheld)", all(seen.get(f) in (None, 0) for f in POLICY), {f: seen.get(f) for f in POLICY})
		till = frappe.get_attr("erpnext.selling.page.point_of_sale.point_of_sale.get_pos_profile_data")(profile)
		check("the till still receives them (get_pos_profile_data)", all(till.get(f) == 1 for f in POLICY), {f: till.get(f) for f in POLICY})
		c = frappe.get_doc("POS Profile", profile)
		c.allow_discount_change = 0
		try:
			c.save()
		except frappe.PermissionError:
			pass  # a cashier cannot save a POS Profile at all (read only): also fine
		check("cashier cannot change them", frappe.db.get_value("POS Profile", profile, "allow_discount_change") == 1)
		frappe.set_user("Administrator")

		if not frappe.db.exists("Payment Term", "RS-TEST 30 days"):
			frappe.get_doc({"doctype": "Payment Term", "payment_term_name": "RS-TEST 30 days", "invoice_portion": 100, "due_date_based_on": "Day(s) after invoice date", "credit_days": 30}).insert()
		term = {"payment_term": "RS-TEST 30 days", "invoice_portion": 100, "due_date_based_on": "Day(s) after invoice date", "credit_days": 30}
		tpl = frappe.get_doc({"doctype": "Payment Terms Template", "template_name": "RS-TEST Net 30", "terms": [term]}).insert().name

		frappe.set_user(manager)
		customer = frappe.get_doc({"doctype": "Customer", "customer_name": "RS-TEST Credit Customer", "customer_type": "Individual", "payment_terms": tpl}).insert()
		check("manager can set a customer's payment terms", frappe.db.get_value("Customer", customer.name, "payment_terms") == tpl)

		frappe.set_user(cashier)
		doc = frappe.get_doc("Customer", customer.name)
		check("cashier still SEES the payment terms", doc.payment_terms == tpl)
		doc.customer_name, doc.payment_terms = "RS-TEST Credit Customer 2", None
		doc.save()
		got = frappe.db.get_value("Customer", customer.name, ["customer_name", "payment_terms"], as_dict=True)
		check("cashier can edit the name", got.customer_name == "RS-TEST Credit Customer 2")
		check("cashier cannot clear the payment terms", got.payment_terms == tpl, got)
		new = frappe.get_doc({"doctype": "Customer", "customer_name": "RS-TEST Cashier New", "customer_type": "Individual", "payment_terms": tpl}).insert()
		check("terms typed by a cashier on a NEW customer are not stored", not frappe.db.get_value("Customer", new.name, "payment_terms"))

		company = frappe.defaults.get_global_default("company")
		item = frappe.get_all("Item", filters={"is_stock_item": 1, "has_variants": 0, "disabled": 0}, pluck="name", limit=1)[0]
		for who in (manager, cashier):
			frappe.set_user(who)
			si = frappe.get_doc({"doctype": "Sales Invoice", "customer": customer.name, "company": company, "posting_date": today(), "due_date": add_days(today(), 30), "payment_terms_template": tpl, "update_stock": 0, "items": [{"item_code": item, "qty": 1, "rate": 100}]}).insert()
			check(f"{who.split('@')[0]}: an invoice keeps the customer's terms and schedule", frappe.db.get_value("Sales Invoice", si.name, "payment_terms_template") == tpl and frappe.db.count("Payment Schedule", {"parent": si.name}) == 1)
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
	print(f"\n{sum(results)}/{len(results)} manager-field checks passed")
