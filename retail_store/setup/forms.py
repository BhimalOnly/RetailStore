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

import json
import os
import re

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

MODULE = "Retail Store"  # marks the Property Setters this module owns

PROPERTY_TYPES = {"permlevel": "Int", "hidden": "Check", "collapsible": "Check", "collapsible_depends_on": "Code", "depends_on": "Code", "label": "Data", "default": "Text"}
KNOWN_CAPABILITIES = {"crm", "ecommerce", "buying", "hr", "manufacturing", "quality", "support", "assets", "projects", "loyalty", "messaging"}
LAYOUT = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading"}
INERT = {"HTML", "Button"}  # may be hidden (with inert_ok) when only help text or an action nobody needs; never a Section / Column / Tab Break
# findings a reviewed hide may acknowledge (see audit); the hard rules are not on this list
ACKNOWLEDGEABLE = {"controller", "logic", "data", "list", "title", "fetch"}

# kind: hide | collapse | gate | relabel | default | restrict
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
	# ---- Item (the clutter is mostly whole feature areas; the few dead-weight fields are hidden via form_hides.json) ----------
	{"doctype": "Item", "field": "item_code", "property": "label", "value": "Product Code", "kind": "relabel", "why": "The sidebar calls Items Products."},
	{"doctype": "Item", "field": "item_name", "property": "label", "value": "Product Name", "kind": "relabel", "why": "The sidebar calls Items Products."},
	{"doctype": "Item", "field": "item_group", "property": "label", "value": "Product Category", "kind": "relabel", "why": "The sidebar already says Product Categories."},
	{"doctype": "Item", "field": "deferred_accounting_section", "property": "collapsible", "value": 1, "kind": "collapse", "why": "Deferred revenue / expense: an accountant's feature."},
	{
		"doctype": "Item", "field": "deferred_accounting_section", "property": "collapsible_depends_on", "kind": "collapse",
		"value": "eval:doc.enable_deferred_expense || doc.enable_deferred_revenue || doc.no_of_months_exp || doc.no_of_months",
		"why": "Opens when deferred accounting is on.",
	},
	{"doctype": "Item", "field": "customer_details", "property": "collapsible", "value": 1, "kind": "collapse", "why": "A customer's own codes for this product: B2B only."},
	{"doctype": "Item", "field": "customer_details", "property": "collapsible_depends_on", "value": "eval:(doc.customer_items || []).length", "kind": "collapse", "why": "Opens when there are customer codes."},
	{
		"doctype": "Item", "field": "foreign_trade_details", "property": "collapsible_depends_on", "kind": "collapse",
		"value": "eval:doc.country_of_origin || doc.customs_tariff_number",
		"why": "ERPNext already collapses this section but never opens it: it would bury a country or tariff number if there ever is one.",
	},
	# Tabs for features the owner switches on under Capabilities (the toggles reach the browser as frappe.boot.retail_store_capabilities).
	# Each keeps the tab's own ERPNext condition and also shows the tab for any product that already holds data in it.
	{
		"doctype": "Item", "field": "manufacturing", "property": "depends_on", "kind": "gate",
		"value": "eval:doc.is_stock_item && (frappe.boot.retail_store_capabilities.manufacturing || frappe.boot.retail_store_capabilities.ecommerce || doc.is_sub_contracted_item || doc.default_bom || doc.production_capacity || doc.default_manufacturer_part_no || doc.default_item_manufacturer || doc.published_in_website)",
		"why": "Manufacturing is off in a retail starter pack. The tab also shows with the Online Store on, because ERPNext keeps the read-only 'published on website' status in it (backlog: move that field to the Details tab).",
	},
	{
		"doctype": "Item", "field": "quality_tab", "property": "depends_on", "kind": "gate",
		"value": "eval:frappe.boot.retail_store_capabilities.quality || doc.inspection_required_before_purchase || doc.inspection_required_before_delivery || doc.quality_inspection_template",
		"why": "Quality inspection is an optional capability.",
	},
	{
		"doctype": "Item", "field": "purchasing_tab", "property": "depends_on", "kind": "gate",
		"value": "eval:doc.is_purchase_item && (frappe.boot.retail_store_capabilities.buying || doc.purchase_uom || doc.min_order_qty || doc.safety_stock || doc.lead_time_days || doc.last_purchase_rate || doc.delivered_by_supplier || (doc.supplier_items || []).length || doc.country_of_origin || doc.customs_tariff_number)",
		"why": "Buying is an optional capability.",
	},
	# ---- Item Price ----------------------------------------------------------------------------------------------
	{"doctype": "Item Price", "field": "price_list_rate", "property": "label", "value": "Price", "kind": "relabel", "why": "Plain word."},
	# ---- Manager-only fields (permlevel 1): on most doctypes everyone who can open the document still SEES them; only Store Manager /
	# Store Owner / Store Admin can change them (setup/roles.py apply_level1_permissions grants exactly that) ----------
	{"doctype": "Customer", "field": "payment_terms", "property": "permlevel", "value": 1, "kind": "restrict", "why": "The customer's default payment terms: a credit decision for a manager, not for the till."},
	{"doctype": "Customer", "field": "credit_limits", "property": "permlevel", "value": 1, "kind": "restrict", "why": "Per-company credit limits: a credit decision for a manager, not for the till."},
	{"doctype": "Sales Order", "field": "payment_terms_template", "property": "permlevel", "value": 1, "kind": "restrict", "why": "Setting a customer's payment terms (e.g. Net 30) is a manager's call; the till can still see them."},
	{"doctype": "Sales Order", "field": "payment_schedule", "property": "permlevel", "value": 1, "kind": "restrict", "why": "The due-date schedule that follows the payment terms: manager-set, visible to the till."},
	{"doctype": "Sales Invoice", "field": "payment_terms_template", "property": "permlevel", "value": 1, "kind": "restrict", "why": "Setting a customer's payment terms (e.g. Net 30) is a manager's call; the till can still see them."},
	{"doctype": "Sales Invoice", "field": "payment_schedule", "property": "permlevel", "value": 1, "kind": "restrict", "why": "The due-date schedule that follows the payment terms: manager-set, visible to the till."},
	{"doctype": "POS Invoice", "field": "payment_terms_template", "property": "permlevel", "value": 1, "kind": "restrict", "why": "Setting a customer's payment terms (e.g. Net 30) is a manager's call; the till can still see them."},
	{"doctype": "POS Invoice", "field": "payment_schedule", "property": "permlevel", "value": 1, "kind": "restrict", "why": "The due-date schedule that follows the payment terms: manager-set, visible to the till."},
	# POS Profile till policies: unlike the payment terms above, the till roles get NO level-1 read, so only managers see them
	{"doctype": "POS Profile", "field": "allow_discount_change", "property": "permlevel", "value": 1, "kind": "restrict", "why": "Whether the till may edit a discount is a store policy a manager sets per location; the till itself still honours it."},
	{"doctype": "POS Profile", "field": "allow_rate_change", "property": "permlevel", "value": 1, "kind": "restrict", "why": "Whether the till may edit an item's price is a store policy a manager sets per location; the till itself still honours it."},
	{"doctype": "POS Profile", "field": "ignore_pricing_rule", "property": "permlevel", "value": 1, "kind": "restrict", "why": "Switching pricing rules off for a location is a manager's policy call; the till itself still honours it."},
	{"doctype": "POS Profile", "field": "validate_stock_on_save", "property": "permlevel", "value": 1, "kind": "restrict", "why": "Whether a sale is blocked when stock is short is a manager's policy call; the till itself still honours it."},
]


# Hides generated from the field review (setup/form_hides.json: doctype, field, reason). Each one passed audit() when it was
# added; audit() runs again on every migrate and refuses any that no longer does, so a bad entry can never reach a form.
FORM_CHANGES.extend(
	{
		"doctype": h["doctype"], "field": h["field"], "property": h.get("property", "hidden"), "value": h.get("value", 1), "kind": h.get("kind", "hide"), "why": h["why"],
		**{k: h[k] for k in ("ack", "filled_ok", "inert_ok") if h.get(k)},
	}
	for h in json.load(open(os.path.join(os.path.dirname(__file__), "form_hides.json")))
)


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


def _fields_in_tab(meta, tab_fieldname):
	inside, found = [], False
	for f in meta.fields:
		if f.fieldname == tab_fieldname:
			found = True
			continue
		if found:
			if f.fieldtype == "Tab Break":
				break
			if f.fieldtype not in ("Section Break", "Column Break"):
				inside.append(f)
	return inside


def _fills_itself(field, changes):
	"""A required field nobody has to type: read-only (derived), fetched from its source, or with a default (ERPNext's own or one of ours)."""
	if field.read_only or field.fetch_from or _truthy_default(field):
		return True
	return any(c["doctype"] == field.parent and c["field"] == field.fieldname and c["property"] == "default" and str(c["value"]).strip() for c in changes)


def _truthy_default(field):
	return str(field.default or "").strip() not in ("", "0", "0.0", "0.00", "0.000")


def _normal(expression):
	"""An expression without its "eval:" prefix and whitespace; a bare field name means doc.<field>."""
	text = str(expression or "").strip()
	if text.startswith("eval:"):
		return re.sub(r"\s+", "", text[5:])
	return f"doc.{text}" if re.fullmatch(r"\w+", text) else re.sub(r"\s+", "", text)


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
			# A reviewed hide names, in `ack`, exactly which of the findings below it has been checked and judged harmless (a
			# value only ever read; nothing needs the field's own widget or a person typing it). Anything not acknowledged
			# still refuses, so a NEW finding after an ERPNext update blocks the hide at the next migrate. The hard rules
			# (required, conditionally required, unique, layout) cannot be acknowledged: required has its own two-key carve-out.
			ack = set(change.get("ack") or [])
			unknown = ack - ACKNOWLEDGEABLE
			if unknown:
				problems.append((change, f"unknown ack {sorted(unknown)}"))

			def finding(category, message):
				if category not in ack:
					problems.append((change, message))

			if field.reqd:
				# only a field that fills itself (read-only, a default, or fetched) and is flagged filled_ok: never one a person must type
				if not (change.get("filled_ok") and _fills_itself(field, changes or FORM_CHANGES)):
					problems.append((change, "required: never hide"))
			if field.mandatory_depends_on:
				problems.append((change, "conditionally required: never hide"))
			if field.fieldtype in LAYOUT and not (field.fieldtype in INERT and change.get("inert_ok")):
				problems.append((change, "hide fields, not layout (a hidden section hides its fields)"))
			if field.unique:
				problems.append((change, "unique: other records depend on it"))
			if field.in_list_view or field.in_standard_filter or field.in_global_search:
				finding("list", "shown in lists, filters or search")
			if fn in (meta.search_fields or "").replace(" ", "").split(",") or fn in (meta.title_field, meta.image_field, meta.sort_field):
				finding("title", "a search / title / image / sort field of the doctype")
			for other in meta.fields:
				if other.fieldname == fn:
					continue
				logic = " ".join(str(other.get(k) or "") for k in ("depends_on", "mandatory_depends_on", "read_only_depends_on", "fetch_from", "collapsible_depends_on"))
				if re.search(r"\b%s\b" % re.escape(fn), logic):
					finding("logic", f"read by the logic of {other.fieldname}")
			if re.search(r"\b%s\b" % re.escape(fn), _controller_text(meta)):
				finding("controller", "mentioned in the doctype's own controller / form script")
			for parent, fetcher, fetch_from in frappe.db.sql(
				"select parent, fieldname, fetch_from from tabDocField where fetch_from like %s union select dt, fieldname, fetch_from from `tabCustom Field` where fetch_from like %s",
				(f"%.{fn}", f"%.{fn}"),
			):
				link = frappe.get_meta(parent).get_field(fetch_from.split(".")[0])
				if link and link.options == dt:
					finding("fetch", f"copied onto {parent}.{fetcher} (fetch_from)")
			if _site_data(dt, field) and not change.get("has_data_ok"):
				finding("data", "holds data on this site")
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
					if f.fieldtype not in LAYOUT and not f.hidden and not f.read_only and not _truthy_default(f) and not re.search(r"\b%s\b" % re.escape(f.fieldname), change["value"]):
						problems.append((change, f"does not open for data in {f.fieldname}"))
		elif kind == "gate":
			# show a TAB only when a capability is on, or when the record already holds data in it (so data is never
			# hidden from someone who needs it), and ALWAYS keeping the tab's own condition
			if field.fieldtype != "Tab Break" or change["property"] != "depends_on":
				problems.append((change, "only a Tab Break's depends_on can be gated"))
				continue
			inside = _fields_in_tab(meta, fn)
			if any(f.reqd or f.mandatory_depends_on for f in inside):
				problems.append((change, "the tab contains a required or conditionally required field"))
			expression = str(change["value"])
			if not expression.startswith("eval:"):
				problems.append((change, "must be an eval: expression"))
			flat = _normal(expression)
			original = frappe.db.get_value("DocField", {"parent": dt, "fieldname": fn}, "depends_on")
			if original and _normal(original) not in flat:
				problems.append((change, f"drops the tab's own condition ({original})"))
			caps = re.findall(r"retail_store_capabilities\.(\w+)", expression)
			if not caps:
				problems.append((change, "does not look at any capability"))
			if any(c not in KNOWN_CAPABILITIES for c in caps):
				problems.append((change, "unknown capability"))
			for f in inside:
				if f.fieldtype in LAYOUT or f.hidden or _truthy_default(f):
					continue
				if not re.search(r"doc\.%s\b" % re.escape(f.fieldname), flat):
					problems.append((change, f"does not show the tab for data in {f.fieldname}"))
		elif kind == "restrict":
			if change["property"] != "permlevel" or str(change["value"]) != "1":
				problems.append((change, "only permlevel 1 is supported"))
			if field.reqd or field.mandatory_depends_on:
				problems.append((change, "required: staff who cannot edit it could not save the document"))
			if field.fieldtype in LAYOUT:
				problems.append((change, "restrict fields, not layout"))
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
def _delete_setter(name):
	"""Delete one Property Setter. frappe.delete_doc would queue a delete_dynamic_links job per setter (a Property Setter has no
	dynamic links), and a few hundred removals in one migrate trip Frappe's "Too many queued background jobs" guard. The callers
	clear the doctype caches themselves."""
	frappe.db.delete("Property Setter", {"name": name})


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
			_delete_setter(name)
			touched.add(doc.doc_type)
	for name, change in wanted.items():
		value = str(change["value"])
		existing = frappe.db.get_value("Property Setter", name, ["value", "module"], as_dict=True)
		if existing and existing.value == value and existing.module == MODULE:
			continue
		if existing:
			_delete_setter(name)
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
		_delete_setter(name)
	for dt in doctypes:
		frappe.clear_cache(doctype=dt)
