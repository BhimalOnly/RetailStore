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

# ALLOWLIST: the only workspaces any desk user may open. Everything else, including
# workspaces added later by installing CRM, Online Store, HR..., is denied unless the
# user holds a back-office role or a role explicitly set on that workspace.
# ("Home" is NOT here: it is the Setup landing with Company, Users and stock value.)
OPEN_WORKSPACES = {"Retail Store"}
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


# Optional-capability workspaces (Retail Store Settings > Capabilities). Store Owner holds their
# doctype grants (setup/capabilities.py); Store Admin does not, so it gets no door to an empty room.
OPTIONAL_CAPABILITY_WORKSPACES = {"Payroll", "CRM", "Buying", "Assets", "Projects", "Manufacturing", "Quality", "Support"}
OWNER_LEVEL = ["System Manager", "Store Owner"]


def allowed_roles_for(workspace):
	"""Roles that may open `workspace`, or None for the allowlisted open workspaces."""
	if workspace in OPEN_WORKSPACES or workspace in LEAVE_ALONE:
		return None
	if workspace in DEVELOPER_ONLY:
		return ["System Manager"]
	if workspace in OPTIONAL_CAPABILITY_WORKSPACES:
		return OWNER_LEVEL + NATIVE_ROLES.get(workspace, [])
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
	"""Allowlist check (module visibility stays navigation).

	Allowed when: the workspace is on the allowlist, OR the user holds one of the roles set
	on it, OR (no roles set yet, e.g. created since the last migrate) the user holds a
	back-office role. A workspace with no roles is therefore DENIED to retail staff."""
	if workspace_name in OPEN_WORKSPACES:
		return True
	user_roles = frappe.get_roles(user)
	roles = frappe.get_all("Has Role", filters={"parent": workspace_name, "parenttype": "Workspace"}, pluck="role")
	if not roles:
		return bool(has_common(user_roles, BACK_OFFICE))
	return bool(has_common(user_roles, roles))


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
	from retail_store.navigation import trim_workspace_page

	return trim_workspace_page(core_get_desktop_page(page))


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


# --- Module dashboards (/desk/<module>/dashboard-view/<Name>) ----------------------------
# Dashboard documents carry "Desk User: read", so the rail's Stock / Selling / Accounts
# buttons opened ERPNext's module dashboards (stock value, sales/purchase totals) for every
# retail role. Same default-deny as workspaces: only back-office or native module roles.

DASHBOARD_ROLES = sorted(set(BACK_OFFICE + [r for roles in NATIVE_ROLES.values() for r in roles] + ["Dashboard Manager"]))


def dashboard_has_permission(doc, ptype=None, user=None, debug=False):
	return bool(has_common(frappe.get_roles(user or frappe.session.user), DASHBOARD_ROLES))


def dashboard_query_conditions(user=None, doctype=None):
	if has_common(frappe.get_roles(user or frappe.session.user), DASHBOARD_ROLES):
		return ""
	return "1=0"


def _require_dashboard_access(dashboard_name):
	if not has_common(frappe.get_roles(), DASHBOARD_ROLES):
		frappe.throw(frappe._("Not permitted to open dashboard {0}").format(dashboard_name), frappe.PermissionError)


@frappe.whitelist()
def get_permitted_cards(dashboard_name):
	"""core get_permitted_cards, but only for roles allowed to open module dashboards."""
	from frappe.desk.doctype.dashboard.dashboard import get_permitted_cards as core

	_require_dashboard_access(dashboard_name)
	return core(dashboard_name)


@frappe.whitelist()
def get_permitted_charts(dashboard_name):
	from frappe.desk.doctype.dashboard.dashboard import get_permitted_charts as core

	_require_dashboard_access(dashboard_name)
	return core(dashboard_name)


# Theme / generic Desk pages that retail users must not open: the theme's own home ("Today's View": widget builder,
# workspace switcher, raw doctype counts), the apps launcher that names ERPNext / Frappe HR, a generic dashboard
# viewer and two HR pages. A Custom Role can only ADD roles to a Page, so these are refused where Frappe loads a
# page instead. ("desktop" is deliberately not here: Frappe routes through it; landing.js redirects it.)
SYSTEM_MANAGER_PAGES = {"smart-home", "all-apps", "dashboard-view", "organizational-chart", "team-updates"}
# the Accountant keeps the ERPNext app, whose "Dashboard" links open the generic dashboard viewer
ALSO_ALLOWED = {"dashboard-view": {"Accounts User", "Accounts Manager"}}


@frappe.whitelist(allow_guest=True)
@frappe.read_only()
def getpage(name: str):
	"""Frappe's getpage, but the generic theme pages above open for System Manager only."""
	from frappe.desk.desk_page import getpage as core_getpage

	roles = set(frappe.get_roles())
	if name in SYSTEM_MANAGER_PAGES and frappe.session.user != "Administrator" and not roles & ({"System Manager"} | ALSO_ALLOWED.get(name, set())):
		frappe.throw(frappe._("Not permitted to open page {0}").format(name), frappe.PermissionError)
	return core_getpage(name)
