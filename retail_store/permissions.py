"""Row-level access for documents that move stock BETWEEN locations.

Native User Permissions require EVERY warehouse field on a document to be an
allowed value, which would hide a "Main -> Store A" transfer from the Store A
manager. For Stock Entry and Material Request we instead show a document when
ANY of its warehouses (header, item rows, or the final destination of an
in-transit move) belongs to the user, or when the user created it.

Users without warehouse User Permissions (Store Owner, Accounts Manager,
System Manager) are not restricted. Note: has_permission hooks can only deny,
never grant, so role permissions still decide create/submit rights.
"""

import frappe

from retail_store.location import get_user_warehouses

FINAL_DESTINATION = "rs_final_destination"


def _in(column, warehouses):
	return "{0} in ({1})".format(column, ", ".join(frappe.db.escape(w) for w in warehouses))


def stock_entry_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	warehouses = get_user_warehouses(user)
	if not warehouses:
		return ""

	conditions = [
		_in("`tabStock Entry`.from_warehouse", warehouses),
		_in("`tabStock Entry`.to_warehouse", warehouses),
		_in(f"`tabStock Entry`.{FINAL_DESTINATION}", warehouses),
		"`tabStock Entry`.owner = {0}".format(frappe.db.escape(user)),
		"""exists (select 1 from `tabStock Entry Detail` sed
			where sed.parent = `tabStock Entry`.name and sed.parenttype = 'Stock Entry'
			and ({0} or {1}))""".format(_in("sed.s_warehouse", warehouses), _in("sed.t_warehouse", warehouses)),
		# In-transit legs created from a Material Request: destination lives on the request.
		"""exists (select 1 from `tabStock Entry Detail` sed
			join `tabMaterial Request Item` mri on mri.name = sed.material_request_item
			where sed.parent = `tabStock Entry`.name and sed.parenttype = 'Stock Entry'
			and {0})""".format(_in("mri.warehouse", warehouses)),
	]
	return "(" + " or ".join(conditions) + ")"


def material_request_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	warehouses = get_user_warehouses(user)
	if not warehouses:
		return ""

	conditions = [
		_in("`tabMaterial Request`.set_warehouse", warehouses),
		_in("`tabMaterial Request`.set_from_warehouse", warehouses),
		"`tabMaterial Request`.owner = {0}".format(frappe.db.escape(user)),
		"""exists (select 1 from `tabMaterial Request Item` mri
			where mri.parent = `tabMaterial Request`.name and mri.parenttype = 'Material Request'
			and ({0} or {1}))""".format(_in("mri.warehouse", warehouses), _in("mri.from_warehouse", warehouses)),
	]
	return "(" + " or ".join(conditions) + ")"


def stock_entry_warehouses(doc):
	found = {doc.get("from_warehouse"), doc.get("to_warehouse"), doc.get(FINAL_DESTINATION)}
	mr_items = []
	for d in doc.get("items") or []:
		found.update((d.get("s_warehouse"), d.get("t_warehouse")))
		if d.get("material_request_item"):
			mr_items.append(d.material_request_item)
	if mr_items:
		found.update(
			frappe.get_all("Material Request Item", filters={"name": ["in", mr_items]}, pluck="warehouse")
		)
	found.discard(None)
	found.discard("")
	return found


def material_request_warehouses(doc):
	found = {doc.get("set_warehouse"), doc.get("set_from_warehouse")}
	for d in doc.get("items") or []:
		found.update((d.get("warehouse"), d.get("from_warehouse")))
	found.discard(None)
	found.discard("")
	return found


def _has_location_access(doc, user, doc_warehouses):
	warehouses = get_user_warehouses(user)
	if not warehouses:
		return True
	if doc.get("owner") == user or doc.is_new():
		# Creating is allowed; validate hooks keep new documents inside the user's locations.
		return True
	found = doc_warehouses(doc)
	return not found or bool(found & set(warehouses))


def stock_entry_has_permission(doc, ptype=None, user=None, debug=False):
	return _has_location_access(doc, user or frappe.session.user, stock_entry_warehouses)


def material_request_has_permission(doc, ptype=None, user=None, debug=False):
	return _has_location_access(doc, user or frappe.session.user, material_request_warehouses)


# --- Stock figures (quantity, valuation, stock value) -----------------------------------
# ERPNext lets any role with read on Bin / Stock Ledger Entry see EVERY warehouse, which
# bypasses a store user's Warehouse User Permission and leaks other locations' stock value
# (e.g. the "Total Stock Value" number card, or GET /api/resource/Bin). Scope both to the
# user's own warehouses; users with no warehouse restriction (Store Owner...) are unchanged.


def _warehouse_conditions(doctype, user=None):
	user = user or frappe.session.user
	warehouses = get_user_warehouses(user)
	if not warehouses:
		return ""
	return _in(f"`tab{doctype}`.warehouse", warehouses)


def bin_query_conditions(user=None, doctype=None):
	return _warehouse_conditions("Bin", user)


def stock_ledger_entry_query_conditions(user=None, doctype=None):
	return _warehouse_conditions("Stock Ledger Entry", user)


def _warehouse_has_permission(doc, user=None):
	warehouses = get_user_warehouses(user or frappe.session.user)
	return not warehouses or not doc.get("warehouse") or doc.get("warehouse") in warehouses


def bin_has_permission(doc, ptype=None, user=None, debug=False):
	return _warehouse_has_permission(doc, user)


def stock_ledger_entry_has_permission(doc, ptype=None, user=None, debug=False):
	return _warehouse_has_permission(doc, user)


# --- Narrow client lookups on doctypes till staff may only SELECT -----------------------
# The POS screen asks frappe.client.get_value for Account.account_currency of the debtors
# account, which needs READ on Account; granting read would expose the whole chart of
# accounts. Allow exactly these harmless lookups (and only for an account, by exact name).
SAFE_SELECT_LOOKUPS = {"Account": {"account_currency"}}


@frappe.whitelist()
def get_value(doctype, fieldname, filters=None, as_dict=True, debug=False, parent=None):
	from frappe.client import get_safe_filters
	from frappe.client import get_value as core_get_value

	allowed = SAFE_SELECT_LOOKUPS.get(doctype)
	if allowed and not frappe.has_permission(doctype, "read"):
		try:
			fields = frappe.parse_json(fieldname)
		except (TypeError, ValueError):
			fields = fieldname
		fields = [fields] if isinstance(fields, str) else fields
		safe_filters = get_safe_filters(filters)
		if isinstance(safe_filters, str):
			safe_filters = {"name": safe_filters}
		by_name = isinstance(safe_filters, dict) and set(safe_filters) == {"name"} and isinstance(safe_filters["name"], str)
		if (
			by_name
			and isinstance(fields, list)
			and set(fields) <= allowed
			and frappe.has_permission(doctype, "select")
		):
			value = frappe.db.get_value(doctype, safe_filters["name"], fields, as_dict=True) or {}
			if as_dict:
				return value
			return value.get(fields[0]) if len(fields) == 1 else [value.get(f) for f in fields]
	return core_get_value(doctype, fieldname, filters, as_dict, debug, parent)
