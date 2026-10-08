"""Location-based access: which warehouses (stores) a staff member works at.

The source of truth is native Frappe **User Permission** records (allow =
Warehouse). Retail Staff Access is only a convenience form that writes them:
one User Permission per (warehouse x doctype listed in Retail Store Settings),
each scoped with "Applicable For" so it restricts transactions only and never
blocks read-only reports such as Stock Balance.
"""

import frappe
from frappe.utils import cint
from frappe.utils.nestedset import get_descendants_of

WAREHOUSE = "Warehouse"
POS_PROFILE = "POS Profile"


def _lines(text):
	return [line.strip() for line in (text or "").splitlines() if line.strip()]


def get_scoped_doctypes():
	settings = frappe.get_cached_doc("Retail Store Settings")
	return _lines(settings.location_scoped_doctypes), _lines(settings.pos_scoped_doctypes)


def get_user_warehouses(user=None):
	"""Warehouses the user is restricted to, including children of group warehouses.

	Returns None when the user has no warehouse restriction at all (e.g. Store Owner),
	which callers treat as "sees every location".
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return None

	cache_key = f"retail_store_user_warehouses::{user}"
	if (cached := frappe.cache.get_value(cache_key)) is not None:
		return cached or None

	assigned = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": WAREHOUSE},
		pluck="for_value",
		distinct=True,
	)
	warehouses = set(assigned)
	for wh in assigned:
		if cint(frappe.db.get_value(WAREHOUSE, wh, "is_group")):
			warehouses.update(get_descendants_of(WAREHOUSE, wh, ignore_permissions=True))

	result = sorted(warehouses)
	frappe.cache.set_value(cache_key, result, expires_in_sec=300)
	return result or None


def clear_user_warehouse_cache(user):
	frappe.cache.delete_value(f"retail_store_user_warehouses::{user}")


def _desired_permissions(access):
	"""(allow, for_value, applicable_for, is_default) tuples the access doc should produce."""
	if not cint(access.enabled):
		return set()

	scoped, pos_scoped = get_scoped_doctypes()
	desired = set()
	for row in access.locations:
		for dt in scoped:
			desired.add((WAREHOUSE, row.warehouse, dt, cint(row.is_default)))

	warehouses = [row.warehouse for row in access.locations]
	default_wh = next((row.warehouse for row in access.locations if row.is_default), None)
	if warehouses and pos_scoped:
		profiles = frappe.get_all(
			POS_PROFILE,
			filters={"warehouse": ["in", warehouses], "disabled": 0},
			fields=["name", "warehouse"],
		)
		default_profile = next((p.name for p in profiles if p.warehouse == default_wh), None)
		for p in profiles:
			for dt in pos_scoped:
				desired.add((POS_PROFILE, p.name, dt, int(p.name == default_profile)))
	return desired


def _managed_filters(user):
	scoped, pos_scoped = get_scoped_doctypes()
	return [
		({"user": user, "allow": WAREHOUSE, "apply_to_all_doctypes": 0}, set(scoped)),
		({"user": user, "allow": POS_PROFILE, "apply_to_all_doctypes": 0}, set(pos_scoped)),
	]


def sync_location_permissions(access):
	"""Make the user's managed User Permissions match the Retail Staff Access doc."""
	desired = _desired_permissions(access)
	existing = {}
	for filters, managed_doctypes in _managed_filters(access.user):
		for up in frappe.get_all(
			"User Permission",
			filters=filters,
			fields=["name", "allow", "for_value", "applicable_for", "is_default"],
		):
			if up.applicable_for in managed_doctypes:
				existing[(up.allow, up.for_value, up.applicable_for, cint(up.is_default))] = up.name

	for key, name in existing.items():
		if key not in desired:
			frappe.delete_doc("User Permission", name, ignore_permissions=True)

	# Insert defaults last so a stale default never blocks the new one.
	for allow, for_value, applicable_for, is_default in sorted(desired - set(existing), key=lambda k: k[3]):
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": access.user,
				"allow": allow,
				"for_value": for_value,
				"apply_to_all_doctypes": 0,
				"applicable_for": applicable_for,
				"is_default": is_default,
			}
		).insert(ignore_permissions=True)

	_add_user_to_pos_profiles(access)
	clear_user_warehouse_cache(access.user)


def _add_user_to_pos_profiles(access):
	"""List the user on the POS Profiles of their stores so POS offers the right till."""
	if not cint(access.enabled):
		return
	warehouses = [row.warehouse for row in access.locations]
	if not warehouses:
		return
	for name in frappe.get_all(POS_PROFILE, filters={"warehouse": ["in", warehouses]}, pluck="name"):
		profile = frappe.get_doc(POS_PROFILE, name)
		if not any(u.user == access.user for u in profile.applicable_for_users):
			profile.append("applicable_for_users", {"user": access.user})
			profile.flags.retail_store_skip_resync = True
			profile.save(ignore_permissions=True)


def clear_location_permissions(user):
	for filters, managed_doctypes in _managed_filters(user):
		for up in frappe.get_all("User Permission", filters=filters, fields=["name", "applicable_for"]):
			if up.applicable_for in managed_doctypes:
				frappe.delete_doc("User Permission", up.name, ignore_permissions=True)
	clear_user_warehouse_cache(user)


def resync_all():
	"""Re-apply every Retail Staff Access record (after changing the scoped doctype lists)."""
	for name in frappe.get_all("Retail Staff Access", pluck="name"):
		sync_location_permissions(frappe.get_doc("Retail Staff Access", name))


def resync_users_for_pos_profile(doc, method=None):
	"""A new or moved POS Profile changes which users it should be scoped to."""
	if doc.flags.retail_store_skip_resync or not doc.warehouse:
		return
	users = frappe.get_all(
		"Retail Staff Location", filters={"warehouse": doc.warehouse, "parenttype": "Retail Staff Access"}, pluck="parent"
	)
	for name in set(users):
		sync_location_permissions(frappe.get_doc("Retail Staff Access", name))


def set_header_warehouse(doc, method=None):
	"""Fill Sales/POS Invoice 'Set Source Warehouse' when every row uses the same one.

	Native User Permissions filter list views on header fields only, so an
	invoice with an empty header warehouse would be visible to every store.
	"""
	if doc.get("set_warehouse"):
		return
	warehouses = {d.warehouse for d in doc.get("items") or [] if d.get("warehouse")}
	if len(warehouses) == 1:
		doc.set_warehouse = warehouses.pop()
