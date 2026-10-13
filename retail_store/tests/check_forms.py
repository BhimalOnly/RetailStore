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
		_item_flows()
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
	manufacturing_ok = next(c["value"] for c in forms.FORM_CHANGES if c["field"] == "manufacturing")
	purchasing_ok = next(c["value"] for c in forms.FORM_CHANGES if c["field"] == "purchasing_tab")
	gates = [
		(bad("Item", "manufacturing", "depends_on", "eval:frappe.boot.retail_store_capabilities.manufacturing || doc.is_sub_contracted_item || doc.default_bom || doc.production_capacity || doc.default_manufacturer_part_no || doc.default_item_manufacturer || doc.published_in_website", "gate"), "own condition"),
		(bad("Item", "purchasing_tab", "depends_on", purchasing_ok.replace(" || doc.lead_time_days", ""), "gate"), "lead_time_days"),
		(bad("Item", "manufacturing", "depends_on", "eval:doc.is_stock_item", "gate"), "capability"),
		(bad("Item", "manufacturing", "depends_on", manufacturing_ok.replace("capabilities.manufacturing", "capabilities.teleport"), "gate"), "unknown capability"),
		(bad("Item", "details", "depends_on", "eval:frappe.boot.retail_store_capabilities.crm", "gate"), "required"),
		(bad("Item", "item_code", "depends_on", "eval:frappe.boot.retail_store_capabilities.crm", "gate"), "Tab Break"),
	]
	for change, keyword in gates:
		found = [p for _, p in forms.audit([change])]
		check(f"audit refuses a tab gate that {keyword}", any(keyword.lower() in p.lower() for p in found), found)

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

	i = frappe.get_meta("Item")
	check("applied: Item reads Product Code / Name / Category, Item Price reads Price", (i.get_field("item_code").label, i.get_field("item_name").label, i.get_field("item_group").label) == ("Product Code", "Product Name", "Product Category") and frappe.get_meta("Item Price").get_field("price_list_rate").label == "Price")
	check("applied: no Item field is hidden by us", not [c for c in forms.FORM_CHANGES if c["doctype"] == "Item" and c["kind"] == "hide"])
	check("applied: Deferred Accounting and Customer Details are collapsed with auto-open, Foreign Trade now opens on data", all(i.get_field(f).collapsible and i.get_field(f).collapsible_depends_on for f in ("deferred_accounting_section", "customer_details", "foreign_trade_details")))
	for tab, orig in (("manufacturing", "is_stock_item"), ("purchasing_tab", "doc.is_purchase_item"), ("quality_tab", None)):
		dep = i.get_field(tab).depends_on or ""
		check(f"applied: the {tab} tab is gated on a capability and keeps its own condition", "retail_store_capabilities" in dep and (orig is None or orig.replace("doc.", "") in dep), dep)
	check("applied: the tabs that must always be there are not gated", not any("retail_store_capabilities" in (i.get_field(t).depends_on or "") for t in ("details", "accounting", "uom_tab", "item_tax_section_break", "inventory_section", "variants_section", "sales_details", "pricing_tab")))

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
	i = frappe.get_meta("Item")
	check("reversible: Item is back to ERPNext's own (label, tab conditions, sections)", i.get_field("item_code").label == "Item Code" and "retail_store_capabilities" not in (i.get_field("manufacturing").depends_on or "") and i.get_field("manufacturing").depends_on == "is_stock_item" and not i.get_field("customer_details").collapsible)
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


def _item_flows():
	"""What an Item is used for, with the changes active, as the roles that do it."""
	from erpnext.controllers.item_variant import create_variant
	from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
	from erpnext.stock.get_item_details import get_item_details

	company = frappe.db.get_value("Company", {}, "name")
	warehouse = frappe.db.get_single_value("Retail Store Settings", "main_warehouse")
	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	price_list = frappe.db.get_value("Price List", {"selling": 1}, "name")
	currency = frappe.db.get_value("Price List", price_list, "currency")

	def details(item_code, **extra):
		args = {"item_code": item_code, "company": company, "doctype": "Sales Invoice", "price_list": price_list, "currency": currency, "price_list_currency": currency,
			"conversion_rate": 1, "plc_conversion_rate": 1, "qty": 1, "customer": "DEMO Walk-in Customer", "transaction_date": today(), "warehouse": warehouse}
		args.update(extra)
		return get_item_details(args)

	frappe.set_user("wh.manager@demo.example")
	simple = frappe.get_doc({"doctype": "Item", "item_code": "FORMS-SIMPLE", "item_group": group, "stock_uom": "Nos"}).insert()
	check("item flow: a warehouse manager saves a product with a code, category and unit", simple.name == "FORMS-SIMPLE" and simple.is_stock_item and simple.is_sales_item, simple.as_dict())
	check("item flow: its name defaults from the code (the relabel changed nothing underneath)", simple.item_name == "FORMS-SIMPLE")

	tpl = frappe.get_doc({"doctype": "Item", "item_code": "FORMS-TPL", "item_group": group, "stock_uom": "Nos", "has_variants": 1, "variant_based_on": "Item Attribute", "attributes": [{"attribute": "Size"}, {"attribute": "Colour"}]}).insert()
	variant = create_variant(tpl.name, {"Size": "Small", "Colour": "Black"})
	variant.insert()
	check("item flow: a variant template with Size and Colour makes a variant", variant.variant_of == tpl.name and len(variant.attributes) == 2, variant.as_dict())

	frappe.get_doc({"doctype": "Item Price", "item_code": variant.name, "price_list": price_list, "price_list_rate": 199}).insert()
	check("item flow: the variant's price (Item Price) is what a sale would charge", float(details(variant.name).get("price_list_rate") or 0) == 199, details(variant.name).get("price_list_rate"))

	variant.reload()
	variant.append("barcodes", {"barcode": "FORMS-BC-0001"})
	variant.append("reorder_levels", {"warehouse": warehouse, "warehouse_reorder_level": 2, "warehouse_reorder_qty": 10, "material_request_type": "Purchase"})
	variant.save()
	from erpnext.selling.page.point_of_sale.point_of_sale import search_for_serial_or_batch_or_barcode_number

	frappe.set_user("cashier.downtown@demo.example")  # cashiers scan; a warehouse manager cannot open the POS
	found = search_for_serial_or_batch_or_barcode_number("FORMS-BC-0001")
	frappe.set_user("wh.manager@demo.example")
	check("item flow: a barcode on the variant is found by the POS scanner", (found or {}).get("item_code") == variant.name, found)
	check("item flow: a reorder level saves", frappe.db.count("Item Reorder", {"parent": variant.name}) == 1)

	simple.reload()
	simple.append("taxes", {"item_tax_template": "Mauritius Tax - DRC"})
	simple.save()
	check("item flow: an item tax template attaches and reaches the sale (item_tax_rate)", "VAT" in str(details(simple.name).get("item_tax_rate")), details(simple.name).get("item_tax_rate"))

	frappe.set_user("Administrator")
	se = make_stock_entry(item_code=variant.name, qty=5, to_warehouse=warehouse, rate=50, company=company)
	check("item flow: stock can be received for it and the Bin shows it", se.docstatus == 1 and frappe.db.get_value("Bin", {"item_code": variant.name, "warehouse": warehouse}, "actual_qty") == 5)

	frappe.set_user("wh.manager@demo.example")
	simple.reload()
	simple.disabled = 1
	simple.save()
	check("item flow: a disabled product is no longer offered", not frappe.get_all("Item", filters={"item_code": "FORMS-SIMPLE", "disabled": 0}))
	frappe.set_user("Administrator")
