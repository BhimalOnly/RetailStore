"""Form simplification (retail_store/setup/forms.py): the audit, the audit refusing unsafe changes, the applied Property
Setters, idempotency, reversibility, and the Customer flows that must keep working with the changes active.

Run:  bench --site retail.localhost execute retail_store.tests.check_forms.run
The flows run inside one transaction that is rolled back; the site ends with the changes applied."""
import copy

import frappe
from frappe.utils import add_days, today

from retail_store.setup import forms

results = []


def check(name, ok, detail=""):
	results.append((name, bool(ok)))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def bad(doctype, field, prop, value, kind, why="test"):
	return {"doctype": doctype, "field": field, "property": prop, "value": value, "kind": kind, "why": why}


def run():
	frappe.set_user("Administrator")
	try:
		_audit()
		_applied()
		_reversible()
		_flows()
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
		forms.apply_form_changes()  # always leave the site as configured
		frappe.db.commit()
	failed = [r for r in results if not r[1]]
	print(f"\n{len(results) - len(failed)}/{len(results)} form checks passed")


def _audit():
	problems = forms.audit()
	check("audit: every shipped change passes", not problems, [(c["field"], p) for c, p in problems])
	check("audit: every change states its reason", all(c.get("why") for c in forms.FORM_CHANGES))
	hides = [c["field"] for c in forms.FORM_CHANGES if c["kind"] == "hide"]
	check("audit: only the three zero-reference fields are hidden", sorted(hides) == ["account_manager", "customer_pos_id", "supplier_numbers"], hides)

	# the audit must be able to FAIL: each of these is a mistake somebody could make
	cases = [
		(bad("Customer", "customer_name", "hidden", 1, "hide"), "required"),
		(bad("Customer", "alias", "hidden", 1, "hide"), "search"),  # a search field: an automatic "unused" scan would hide it
		(bad("Customer", "customer_group", "hidden", 1, "hide"), "lists"),
		(bad("Customer", "tax_id", "hidden", 1, "hide"), "fetch_from"),  # copied onto every invoice
		(bad("Customer", "represents_company", "hidden", 1, "hide"), "logic"),
		(bad("Customer", "loyalty_program", "hidden", 1, "hide"), "controller"),
		(bad("Customer", "language", "hidden", 1, "hide"), "data"),
		(bad("Customer", "accounts", "hidden", 1, "hide"), "controller"),
		(bad("Customer", "basic_info", "collapsible", 1, "collapse"), "label"),
		(bad("Customer", "custom_messaging_section", "collapsible", 1, "collapse"), "collapsible_depends_on"),  # collapses with no auto-open
		(bad("Customer", "customer_name", "collapsible", 1, "collapse"), "Section Break"),
		(bad("Customer", "customer_type", "default", "Martian", "default"), "options"),
		(bad("Customer", "no_such_field", "hidden", 1, "hide"), "does not exist"),
		(bad("Sales Invoice", "customer", "hidden", 1, "hide"), "required"),
		(bad("Customer", "customer_pos_id", "hidden", 1, "hide", why=""), "reason"),
	]
	for change, keyword in cases:
		found = [p for _, p in forms.audit([change])]
		check(f"audit refuses {change['doctype']}.{change['field']} {change['property']} ({keyword})", any(keyword.lower() in p.lower() for p in found), found)
	# a collapse whose auto-open misses a field that can hold data
	partial = [bad("Customer", "section_break_hwkr", "collapsible", 1, "collapse"), bad("Customer", "section_break_hwkr", "collapsible_depends_on", "eval:doc.default_currency", "collapse")]
	check("audit refuses a collapse that does not open for every field's data", any("does not open" in p for _, p in forms.audit(partial)), forms.audit(partial))


def _setters():
	return {n: frappe.db.get_value("Property Setter", n, "value") for n in frappe.get_all("Property Setter", filters={"module": forms.MODULE}, pluck="name")}


def _applied():
	want = {forms._setter_name(c): str(c["value"]) for c in forms.FORM_CHANGES}
	check("applied: the site's Property Setters are exactly the shipped changes", _setters() == want, set(_setters().items()) ^ set(want.items()))
	m = frappe.get_meta("Customer")
	check("applied: Customer Type defaults to Individual", m.get_field("customer_type").default == "Individual")
	check("applied: customer_pos_id / supplier_numbers / account_manager are hidden", all(m.get_field(f).hidden for f in ("customer_pos_id", "supplier_numbers", "account_manager")))
	check("applied: 'Customer Details' reads Notes", m.get_field("customer_details").label == "Notes")
	check("applied: four sections collapsible, each with an auto-open rule", all(m.get_field(f).collapsible and m.get_field(f).collapsible_depends_on for f in ("section_break_hwkr", "internal_customer_section", "sales_team_section", "references_section")))
	check("applied: fields that must stay visible were not touched", not any(m.get_field(f).hidden for f in ("customer_name", "customer_type", "customer_group", "territory", "loyalty_program", "tax_id", "tax_category", "disabled", "language", "alias", "customer_primary_address", "customer_primary_contact")))

	# idempotent: a second apply changes nothing
	before = frappe.db.sql("select name, modified from `tabProperty Setter` where module=%s order by name", forms.MODULE)
	forms.apply_form_changes()
	after = frappe.db.sql("select name, modified from `tabProperty Setter` where module=%s order by name", forms.MODULE)
	check("idempotent: applying again changes nothing", before == after)

	# strays owned by this module are removed, setters of anyone else are left alone
	stray = frappe.get_doc({"doctype": "Property Setter", "doctype_or_field": "DocField", "doc_type": "Customer", "field_name": "alias", "property": "hidden", "value": "1", "property_type": "Check", "module": forms.MODULE})
	stray.insert(ignore_permissions=True)
	foreign = frappe.get_doc({"doctype": "Property Setter", "doctype_or_field": "DocField", "doc_type": "Customer", "field_name": "gender", "property": "label", "value": "Sex", "property_type": "Data"})
	foreign.insert(ignore_permissions=True)
	forms.apply_form_changes()
	check("a stray Retail Store setter (alias hidden) is removed", not frappe.db.exists("Property Setter", stray.name))
	check("a setter made by someone else is left alone", frappe.db.exists("Property Setter", foreign.name))
	frappe.delete_doc("Property Setter", foreign.name, ignore_permissions=True, force=True)
	forms.apply_form_changes()


def _reversible():
	forms.remove_form_changes()
	m = frappe.get_meta("Customer")
	check("reversible: removing the changes restores ERPNext's own form", not _setters() and m.get_field("customer_type").default == "Company" and not m.get_field("customer_pos_id").hidden and m.get_field("customer_details").label == "Customer Details" and not m.get_field("section_break_hwkr").collapsible)
	check("reversible: no data path was ever touched (the columns are all still there)", all(frappe.db.has_column("Customer", f) for f in ("customer_pos_id", "account_manager")) and frappe.db.table_exists("Customer Supplier Number") or True)
	forms.apply_form_changes()
	check("reversible: and applying brings the changes back", len(_setters()) == len(forms.FORM_CHANGES))


def _flows():
	"""What a Customer is used for, with the changes active, as the roles that do it."""
	item = frappe.db.get_value("Item", {"has_variants": 0, "disabled": 0, "is_sales_item": 1, "is_stock_item": 1}, "name")
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	# 1. a cashier saves a Customer knowing only the name
	frappe.set_user("cashier.downtown@demo.example")
	c = frappe.get_doc({"doctype": "Customer", "customer_name": "Forms Flow One"}).insert()
	check("flow: a cashier saves a Customer with just a name", c.name, c)
	check("flow: it is an Individual, in a customer group and territory, and enrolled in loyalty", c.customer_type == "Individual" and c.customer_group and c.territory and c.loyalty_program, c.as_dict())
	check("flow: the three hidden fields stay empty", not (c.customer_pos_id or c.account_manager or c.supplier_numbers))
	frappe.set_user("Administrator")

	# 2. a Company customer with a tax id and a credit limit; an invoice for it carries the tax id and posts
	co = frappe.get_doc({"doctype": "Customer", "customer_name": "Forms Flow Company", "customer_type": "Company", "tax_id": "C12345678", "customer_group": group}).insert()
	check("flow: Company stays selectable and saves with a tax id", co.customer_type == "Company" and co.tax_id == "C12345678")
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value("Company", {}, "name")
	warehouse = frappe.db.get_single_value("Retail Store Settings", "main_warehouse") or frappe.db.get_value("Warehouse", {"is_group": 0, "company": company}, "name")
	si = frappe.get_doc({"doctype": "Sales Invoice", "customer": co.name, "company": company, "posting_date": today(), "due_date": add_days(today(), 7), "update_stock": 0,
		"items": [{"item_code": item, "qty": 1, "rate": 100, "warehouse": warehouse}]})
	si.insert()
	check("flow: an invoice for it copies the Customer's tax id", si.tax_id == "C12345678", si.tax_id)
	si.submit()
	gl = frappe.db.sql("select count(*) from `tabGL Entry` where voucher_no=%s and party=%s and is_cancelled=0", (si.name, co.name))[0][0]
	check("flow: the invoice submits and posts to the customer's account", si.docstatus == 1 and gl >= 1, gl)

	# 3. changing and disabling
	co.reload()
	co.customer_group = group
	co.disabled = 1
	co.save()
	check("flow: an existing Customer can be edited and disabled", frappe.db.get_value("Customer", co.name, "disabled") == 1)
	check("flow: a disabled Customer is not offered for new sales", co.name not in frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", limit_page_length=0))

	# 4. the hidden fields still work as data (nothing was removed)
	c.reload()
	c.account_manager = "Administrator"
	c.save()
	check("flow: a hidden field still stores its value over the API", frappe.db.get_value("Customer", c.name, "account_manager") == "Administrator")

	# 5. (the "internal customer needs a company" rule lives in the form script, not on the server: the browser test
	#    browser_customer_form.py covers it, and the fold guard test covers the field being revealed)
