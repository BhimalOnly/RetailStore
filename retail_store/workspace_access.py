"""Server-side lock on ERPNext's generic module workspaces (Accounting, Selling, Stock, ...).

Why: Frappe treats workspace visibility as navigation. get_desktop_page() and the
Workspace document API never check Workspace.is_permitted(), so any Desk User can
open /desk/accounting by URL even when the sidebar hides it. Retail staff work from
the trimmed "Retail Store" workspace; the generic ones are for owners/admins and the
native ERPNext back-office roles.

Two halves, both needed:
1. apply_workspace_access() sets `roles` on each workspace (re-run on every migrate,
   because syncing standard workspaces resets them).
2. get_desktop_page() override + Workspace has_permission hook make the server refuse
   (PermissionError -> HTTP 403) instead of merely hiding.
"""

import json

import frappe
from frappe.utils import has_common

# Open to every Desk User; trimmed by their own sidebar / module profile instead.
OPEN_WORKSPACES = {"Retail Store", "Home"}
# Already carry their own roles (Users: System Manager). Never rewritten here.
LEAVE_ALONE = {"Users"}

BACK_OFFICE = ["System Manager", "Store Owner", "Store Admin"]
DEVELOPER_ONLY = {"Build"}

# Native ERPNext roles that legitimately use a module's workspace, so e.g. a real
# accountant keeps Accounting. Retail roles are deliberately NOT in these lists.
NATIVE_ROLES = {
	"Accounting": ["Accounts User", "Accounts Manager"],
	"Financial Reports": ["Accounts User", "Accounts Manager"],
	"Invoicing": ["Accounts User", "Accounts Manager"],
	"Payments": ["Accounts User", "Accounts Manager"],
	"Selling": ["Sales User", "Sales Manager"],
	"Stock": ["Stock User", "Stock Manager"],
	"Buying": ["Purchase User", "Purchase Manager"],
	"Assets": ["Accounts User", "Accounts Manager"],
	"CRM": ["Sales User", "Sales Manager"],
	"Manufacturing": ["Manufacturing User", "Manufacturing Manager"],
	"Projects": ["Projects User", "Projects Manager"],
	"Support": ["Support Team"],
	"Quality": ["Quality Manager"],
}


def allowed_roles_for(workspace):
	"""Roles that may open `workspace`, or None to leave it open to all Desk Users."""
	if workspace in OPEN_WORKSPACES or workspace in LEAVE_ALONE:
		return None
	if workspace in DEVELOPER_ONLY:
		return ["System Manager"]
	return BACK_OFFICE + NATIVE_ROLES.get(workspace, [])


def apply_workspace_access():
	"""Idempotently write the role gate onto every public workspace."""
	for name in frappe.get_all("Workspace", filters={"public": 1}, pluck="name"):
		roles = allowed_roles_for(name)
		if roles is None:
			continue
		roles = sorted({r for r in roles if frappe.db.exists("Role", r)})
		current = sorted(frappe.get_all("Has Role", filters={"parent": name, "parenttype": "Workspace"}, pluck="role"))
		if current == roles:
			continue
		frappe.db.delete("Has Role", {"parent": name, "parenttype": "Workspace"})
		for idx, role in enumerate(roles, start=1):
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parent": name,
					"parenttype": "Workspace",
					"parentfield": "roles",
					"role": role,
					"idx": idx,
				}
			).db_insert()
		frappe.clear_document_cache("Workspace", name)
	frappe.cache.delete_value("desktop_icons")


def _role_allowed(workspace_name, for_user=None, user=None):
	"""Roles-only check (module visibility stays navigation). True when no roles are set."""
	roles = frappe.get_all("Has Role", filters={"parent": workspace_name, "parenttype": "Workspace"}, pluck="role")
	if not roles:
		return True
	return bool(has_common(frappe.get_roles(user), roles))


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Workspace doc API (e.g. /api/resource/Workspace/Accounting): read needs an allowed role.

	Denies only; never grants. Private pages belong to their owner and are untouched."""
	if ptype not in (None, "read", "select"):
		return True
	user = user or frappe.session.user
	if doc.get("for_user"):
		return True
	return _role_allowed(doc.name, user=user)


@frappe.whitelist()
@frappe.read_only()
def get_desktop_page(page: str):
	"""Frappe's get_desktop_page, but refuses workspaces the user's roles don't allow."""
	from frappe.desk.desktop import get_desktop_page as core_get_desktop_page

	options = json.loads(page)
	name = options.get("name")
	if name and frappe.db.exists("Workspace", name):
		doc = frappe.get_cached_doc("Workspace", name)
		if not doc.get("for_user") and not _role_allowed(name):
			frappe.throw(frappe._("Not permitted to open workspace {0}").format(name), frappe.PermissionError)
	return core_get_desktop_page(page)


LANDING_WORKSPACE = "Retail Store"


def set_default_landing(doc, method=None):
	"""User.validate: new desk users land on the Retail Store workspace.

	Uses Frappe's own User.default_workspace (first in the router's landing order). Do NOT
	use boot.home_page: that expects a Page, and for workspace slugs it makes the client
	probe getpage and show "Not permitted" to anyone without Page access."""
	if doc.user_type == "System User" and not doc.get("default_workspace"):
		if frappe.db.exists("Workspace", LANDING_WORKSPACE):
			doc.default_workspace = LANDING_WORKSPACE


def backfill_default_landing():
	"""Give every existing desk user without a choice of their own the Retail Store landing."""
	if not frappe.db.exists("Workspace", LANDING_WORKSPACE):
		return
	for name in frappe.get_all(
		"User", filters={"user_type": "System User", "default_workspace": ["in", ["", None]]}, pluck="name"
	):
		frappe.db.set_value("User", name, "default_workspace", LANDING_WORKSPACE, update_modified=False)
