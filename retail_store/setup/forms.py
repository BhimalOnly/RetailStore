"""Form simplification for retail use: a declarative list of Customize Form changes (Property Setters).

Principles (learned the hard way: a required field that nobody could see broke saving a Customer):
  * COLLAPSE (a Section Break set collapsible, opened automatically when it holds data) and RELABEL / DEFAULT are the
    preferred tools: everything stays one click away.
  * HIDE is only for a field that is provably dead weight (see audit()).
  * Nothing is ever deleted: a hidden field keeps its column, its data and its logic.
  * Every change carries its reason and what was checked. audit() refuses any change that breaks a rule, and
    apply_form_changes() only applies changes that pass it (deny by default).
  * Changes are site-wide (Customize Form is not per role), idempotent, and reversible: they are Property Setters
    marked module "Retail Store"; remove_form_changes() deletes exactly those.

Tests: tests/check_forms.py (the audit, the audit refusing bad changes, reversibility, the flows) and
tests/browser_customer_form.py.
"""

import os
import re

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

MODULE = "Retail Store"  # marks the Property Setters this module owns

PROPERTY_TYPES = {"hidden": "Check", "collapsible": "Check", "collapsible_depends_on": "Code", "label": "Data", "default": "Text"}
LAYOUT = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading"}

# kind: hide | collapse | relabel | default
FORM_CHANGES = [
	# ---- Customer ----------------------------------------------------------------------------------------------
	{
		"doctype": "Customer", "field": "customer_type", "property": "default", "value": "Individual", "kind": "default",
		"why": "A retail customer is a person, not a company: ERPNext defaults to Company, which also hides first / last name. Company stays selectable.",
	},
	{
		"doctype": "Customer", "field": "customer_details", "property": "label", "value": "Notes", "kind": "relabel",
		"why": "Plain word for a free-text note.",
	},
	{
		"doctype": "Customer", "field": "customer_pos_id", "property": "hidden", "value": 1, "kind": "hide",
		"why": "No code in ERPNext, HRMS, webshop or this app reads or writes it; empty on every customer.",
	},
	{
		"doctype": "Customer", "field": "supplier_numbers", "property": "hidden", "value": 1, "kind": "hide",
		"why": "A table of the customer's numbers at suppliers: no code reads it, no data.",
	},
	{
		"doctype": "Customer", "field": "account_manager", "property": "hidden", "value": 1, "kind": "hide",
		"why": "No code reads it; empty on every customer.",
	},
	# collapsed sections open by themselves whenever they hold data, so nothing is ever buried
	{
		"doctype": "Customer", "field": "section_break_hwkr", "property": "collapsible", "value": 1, "kind": "collapse",
		"why": "Defaults (currency, bank account, price list, payment terms): real but rare.",
	},
	{
		"doctype": "Customer", "field": "section_break_hwkr", "property": "collapsible_depends_on", "kind": "collapse",
		"value": "eval:doc.default_currency || doc.default_bank_account || doc.default_price_list || doc.payment_terms",
		"why": "Opens when any default is set.",
	},
	{
		"doctype": "Customer", "field": "internal_customer_section", "property": "collapsible", "value": 1, "kind": "collapse",
		"why": "Inter-company: a multi-company feature, essentially never relevant to one retail store, but functional.",
	},
	{
		"doctype": "Customer", "field": "internal_customer_section", "property": "collapsible_depends_on", "value": "eval:doc.is_internal_customer || doc.represents_company", "kind": "collapse",
		"why": "Opens when the customer is internal.",
	},
	{
		"doctype": "Customer", "field": "sales_team_section", "property": "collapsible", "value": 1, "kind": "collapse",
		"why": "Sales partner / commission: plausible for affiliates, not universal.",
	},
	{
		"doctype": "Customer", "field": "sales_team_section", "property": "collapsible_depends_on", "value": "eval:doc.default_sales_partner || doc.default_commission_rate", "kind": "collapse",
		"why": "Opens when a partner or rate is set.",
	},
	{
		"doctype": "Customer", "field": "references_section", "property": "collapsible", "value": 1, "kind": "collapse",
		"why": "Lead / opportunity / prospect this customer came from (CRM): read-only, empty unless CRM is used.",
	},
	{
		"doctype": "Customer", "field": "references_section", "property": "collapsible_depends_on", "value": "eval:doc.lead_name || doc.opportunity_name || doc.prospect_name", "kind": "collapse",
		"why": "Opens when the customer came from CRM.",
	},
]

APPS = os.path.abspath(os.path.join(os.path.dirname(frappe.__file__), "..", ".."))


# ---- audit ----------------------------------------------------------------------------------------------------------
def _controller_text(meta):
	"""The doctype's own .py / .js, minus the generated type-annotation block (which lists every field)."""
	text = ""
	for app in frappe.get_installed_apps():
		folder = frappe.get_app_path(app, frappe.scrub(meta.module), "doctype", frappe.scrub(meta.name))
		if not os.path.isdir(folder):
			continue
		for name in os.listdir(folder):
			if name.endswith((".py", ".js")) and not name.startswith("test_"):
				body = open(os.path.join(folder, name), errors="ignore").read()
				body = re.sub(r"# begin: auto-generated types.*?# end: auto-generated types", "", body, flags=re.S)
				text += "\n" + body
		break
	return text


def _site_data(doctype, field):
	if field.fieldtype == "Table":
		return bool(frappe.db.sql("select 1 from `tab%s` where parenttype=%%s limit 1" % field.options, doctype))
	if not frappe.db.has_column(doctype, field.fieldname):
		return False
	numeric = field.fieldtype in ("Check", "Int", "Float", "Currency", "Percent")
	cond = "`%s` is not null and `%s` <> %s" % (field.fieldname, field.fieldname, "0" if numeric else "''")
	return bool(frappe.db.sql("select 1 from `tab%s` where %s limit 1" % (doctype, cond)))


def _fields_in_section(meta, section_fieldname):
	inside, found = [], False
	for f in meta.fields:
		if f.fieldname == section_fieldname:
			found = True
			continue
		if found:
			if f.fieldtype in ("Section Break", "Tab Break"):
				break
			if f.fieldtype != "Column Break":
				inside.append(f)
	return inside


def audit(changes=None):
	"""Every rule a change must meet. Returns [(change, problem)]: an empty list means all are safe."""
	problems = []
	for change in FORM_CHANGES if changes is None else changes:
		dt, fn, kind = change["doctype"], change["field"], change["kind"]
		if not frappe.db.exists("DocType", dt):
			problems.append((change, f"{dt} does not exist"))
			continue
		meta = frappe.get_meta(dt)
		field = meta.get_field(fn)
		if not field:
			problems.append((change, f"{dt}.{fn} does not exist"))
			continue
		if change["property"] not in PROPERTY_TYPES:
			problems.append((change, f"property {change['property']} is not supported"))
			continue
		if not change.get("why"):
			problems.append((change, "a change needs its reason"))

		if kind == "hide":
			if field.reqd:
				problems.append((change, "required: never hide"))
			if field.mandatory_depends_on:
				problems.append((change, "conditionally required: never hide"))
			if field.fieldtype in LAYOUT:
				problems.append((change, "hide fields, not layout (a hidden section hides its fields)"))
			if field.unique:
				problems.append((change, "unique: other records depend on it"))
			if field.in_list_view or field.in_standard_filter or field.in_global_search:
				problems.append((change, "shown in lists, filters or search"))
			if fn in (meta.search_fields or "").replace(" ", "").split(",") or fn in (meta.title_field, meta.image_field, meta.sort_field):
				problems.append((change, "a search / title / image / sort field of the doctype"))
			for other in meta.fields:
				if other.fieldname == fn:
					continue
				logic = " ".join(str(other.get(k) or "") for k in ("depends_on", "mandatory_depends_on", "read_only_depends_on", "fetch_from", "collapsible_depends_on"))
				if re.search(r"\b%s\b" % re.escape(fn), logic):
					problems.append((change, f"read by the logic of {other.fieldname}"))
			if re.search(r"\b%s\b" % re.escape(fn), _controller_text(meta)):
				problems.append((change, "mentioned in the doctype's own controller / form script"))
			for parent, fetcher, fetch_from in frappe.db.sql(
				"select parent, fieldname, fetch_from from tabDocField where fetch_from like %s union select dt, fieldname, fetch_from from `tabCustom Field` where fetch_from like %s",
				(f"%.{fn}", f"%.{fn}"),
			):
				link = frappe.get_meta(parent).get_field(fetch_from.split(".")[0])
				if link and link.options == dt:
					problems.append((change, f"copied onto {parent}.{fetcher} (fetch_from)"))
			if _site_data(dt, field) and not change.get("has_data_ok"):
				problems.append((change, "holds data on this site"))
		elif kind == "collapse":
			if field.fieldtype != "Section Break":
				problems.append((change, "only a Section Break can be collapsed"))
				continue
			if not field.label:
				problems.append((change, "a section needs a label to be opened again"))
			inside = _fields_in_section(meta, fn)
			if any(f.reqd for f in inside):
				problems.append((change, "contains a required field"))
			cdep = next((c["value"] for c in (changes or FORM_CHANGES) if c["doctype"] == dt and c["field"] == fn and c["property"] == "collapsible_depends_on"), field.collapsible_depends_on)
			if change["property"] == "collapsible" and not cdep:
				problems.append((change, "needs collapsible_depends_on, so a section holding data opens by itself"))
			if change["property"] == "collapsible_depends_on":
				for f in inside:
					if f.fieldtype not in LAYOUT and not f.hidden and not f.read_only and not re.search(r"\b%s\b" % re.escape(f.fieldname), change["value"]):
						problems.append((change, f"does not open for data in {f.fieldname}"))
		elif kind == "relabel":
			if not str(change["value"]).strip():
				problems.append((change, "empty label"))
		elif kind == "default":
			value = change["value"]
			if field.fieldtype == "Select" and value not in (field.options or "").split("\n"):
				problems.append((change, f"{value!r} is not one of the options"))
			if field.fieldtype == "Link" and not frappe.db.exists(field.options, value):
				problems.append((change, f"{value!r} does not exist"))
		else:
			problems.append((change, f"unknown kind {kind}"))
	return problems


# ---- apply / remove -------------------------------------------------------------------------------------------------
def _setter_name(change):
	return f"{change['doctype']}-{change['field']}-{change['property']}"


def apply_form_changes():
	"""Make the site's Retail Store Property Setters exactly the changes that pass audit(). Idempotent."""
	refused = {id(c) for c, _ in audit()}
	wanted = {_setter_name(c): c for c in FORM_CHANGES if id(c) not in refused}
	managed = {c["doctype"] for c in FORM_CHANGES}
	touched = set()
	for name in frappe.get_all("Property Setter", filters={"module": MODULE}, pluck="name"):
		doc = frappe.get_doc("Property Setter", name)
		if name not in wanted:
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
			touched.add(doc.doc_type)
	for name, change in wanted.items():
		value = str(change["value"])
		existing = frappe.db.get_value("Property Setter", name, ["value", "module"], as_dict=True)
		if existing and existing.value == value and existing.module == MODULE:
			continue
		if existing:
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
		make_property_setter(change["doctype"], change["field"], change["property"], value, PROPERTY_TYPES[change["property"]], validate_fields_for_doctype=False)
		frappe.db.set_value("Property Setter", name, "module", MODULE)
		touched.add(change["doctype"])
	for dt in touched | (managed if not wanted else set()):
		frappe.clear_cache(doctype=dt)
	for change, problem in audit():
		print(f"form change refused ({change['doctype']}.{change['field']} {change['property']}): {problem}")


def remove_form_changes():
	"""Undo every change this module made (nothing else is touched)."""
	doctypes = set()
	for name in frappe.get_all("Property Setter", filters={"module": MODULE}, pluck="name"):
		doctypes.add(frappe.db.get_value("Property Setter", name, "doc_type"))
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
	for dt in doctypes:
		frappe.clear_cache(doctype=dt)
