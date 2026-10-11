"""Owner-controlled extra permissions for shop-floor staff.

Out of the box a Cashier / Attendant sells, counts stock and requests transfers; they cannot book
stock movements or change prices (roles.py, and stock_transfer.py for the transfer types). The Store
Owner can lift that for named people in Retail Store Settings > Stock Transfers > Extra Staff
Permissions. Each row maps to one role (GRANTS); this module keeps those roles in step with the table
and nothing else adds them, so removing a row removes the right.
"""

import frappe
from frappe import _

from retail_store.setup.roles import GRANT_ROLES

GRANTS = {"Receive stock": "Stock Receiver", "Change prices": "Price Editor"}
OWNER_ONLY = {"Store Owner", "System Manager"}


def validate_settings(doc):
	"""Only the Store Owner (or System Manager) may change who has extra permissions."""
	old = doc.get_doc_before_save()
	before = sorted((r.staff, r.permission) for r in (old.get("staff_grants") if old else []) or [])
	after = sorted((r.staff, r.permission) for r in doc.get("staff_grants") or [])
	if before != after and not OWNER_ONLY & set(frappe.get_roles()) and frappe.session.user != "Administrator":
		frappe.throw(_("Only the Store Owner can give or take away extra staff permissions."), frappe.PermissionError)
	seen = set()
	for r in doc.get("staff_grants") or []:
		if (r.staff, r.permission) in seen:
			frappe.throw(_("{0} is listed twice for “{1}”.").format(r.staff, r.permission))
		seen.add((r.staff, r.permission))


def sync_grant_roles(doc):
	"""Make the Stock Receiver / Price Editor roles match the table exactly."""
	wanted = {role: set() for role in GRANT_ROLES}
	for r in doc.get("staff_grants") or []:
		if GRANTS.get(r.permission):
			wanted[GRANTS[r.permission]].add(r.staff)
	for role, users in wanted.items():
		have = set(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"))
		for user in users - have:
			if frappe.db.exists("User", user):
				u = frappe.get_doc("User", user)
				u.append("roles", {"role": role})
				u.save(ignore_permissions=True)
		for user in have - users:
			u = frappe.get_doc("User", user)
			u.roles = [x for x in u.roles if x.role != role]
			u.save(ignore_permissions=True)
