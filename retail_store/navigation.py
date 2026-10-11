"""What the Desk navigation shows each retail role: the app rail and the Retail Store sidebar.

Display only. The 403s in workspace_access.py / permissions.py are the real boundary; this keeps
a role from being offered doors it should not use, and keeps ERPNext / Frappe HR / Framework
branding out of sight (the apps themselves are not renamed: that breaks on every update).

* Rail (solvronix_desk draws one icon per app from get_workspaces): everyone but System Manager
  sees the Retail Store app only.
* Sidebar (boot payload `module_sidebars["Retail Store"]`): each doctype link says which roles
  see it, and is relabelled in shop language. A role not named for a link does not see it
  (deny by default); back-office roles see everything they hold permission for.
* A "People" section carries the HR entry points, since the Frappe HR app icon is gone.
"""

import frappe
from frappe.utils import cint

APP = "retail_store"
BACK_OFFICE = {"System Manager", "Store Owner", "Store Admin"}
STAFF = {"Store Manager", "Store Cashier", "Store Attendant", "Warehouse Manager", "Warehouse Attendant"}

_MANAGER = {"Store Manager"}
_STOCK_HANDS = {"Store Manager", "Store Attendant", "Warehouse Manager", "Warehouse Attendant"}

# link_to -> (shop label, roles beyond back office that see it). Not listed = shown as is.
LINKS = {
	"Sales Invoice": ("Sales", _MANAGER),  # a cashier reprints / returns from POS > Recent Orders
	"Loyalty Program": ("Loyalty", _MANAGER),
	"Stock Balance": ("Stock Levels", _STOCK_HANDS),
	"Material Request": ("Request Transfer", {"Store Manager", "Warehouse Manager"}),
	"Stock Entry": ("Move Stock", {"Store Manager", "Warehouse Manager"}),
	"Stock Reconciliation": ("Stock Count", {"Store Manager", "Warehouse Manager"}),
	"Warehouse": ("Locations", {"Store Manager", "Warehouse Manager"}),
	"Item": ("Products", _STOCK_HANDS),
	"Item Group": ("Product Categories", _MANAGER),
	"Item Attribute": ("Product Options", _MANAGER),
	"Item Price": ("Prices", _MANAGER),
	"POS Opening Entry": ("Till Openings", _MANAGER),  # POS itself opens and closes the till
	"POS Closing Entry": ("Till Closings", _MANAGER),
	"POS Profile": ("Till Setup", _MANAGER),
	"Loyalty Point Entry": ("Points History", _MANAGER),
	# only on the home page cards, not in the sidebar
	"Stock Projected Qty": ("Projected Stock", _STOCK_HANDS),
	"Stock Ledger": ("Stock Movements", _STOCK_HANDS),
	"Sales Register": ("Sales Register", _MANAGER),
	"User": ("User", set()),
	"Retail Store Settings": ("Retail Store Settings", set()),
	"Retail Staff Access": ("Retail Staff Access", set()),
}
SECTIONS = {"Till": "Tills"}

# (doctype, shop label, roles beyond back office) in the People section, when HR is on
PEOPLE = [
	("Employee", "Staff", _MANAGER),
	("Attendance", "Attendance", _MANAGER),
	("Leave Application", "Leave", _MANAGER),
	("Shift Assignment", "Shifts", _MANAGER),
	("Employee Checkin", "Clock Records", _MANAGER),
	("Salary Slip", "Payslips", set()),
	("Payroll Entry", "Run Payroll", set()),
]


# Back office (Store Owner / Store Admin): what the raw Stock / Selling / Accounts module shells used to hold
# that the Retail Store sidebar did not, now that those Dock icons are gone. Shown only where the role
# holds read permission, in shop language.
BACK_OFFICE_LINKS = [
	("Sales Order", "Online Orders"),
	("Delivery Note", "Deliveries"),
	("Payment Entry", "Payments"),
	("Pricing Rule", "Discount Rules"),
	("Price List", "Price Lists"),
	("Mode of Payment", "Payment Methods"),
	("Sales Taxes and Charges Template", "Taxes"),
	("Account", "Chart of Accounts"),
	("UOM", "Units"),
	("Brand", "Brands"),
	("Customer Group", "Customer Groups"),
]


# Reports in the same section (the report opens directly: no Accounting module shell), only for a role the report is
# granted to (roles.REPORT_ROLES): the Store Owner, not Store Admin / Manager / Cashier.
BACK_OFFICE_REPORTS = [("Profit and Loss Statement", "Profit & Loss"), ("Balance Sheet", "Balance Sheet")]


# Optional capabilities (Retail Store Settings > Capabilities) live in ERPNext's own workspaces. With the
# ERPNext app icon gone they are offered here instead, to the owner only (workspace_access.OWNER_LEVEL).
CAPABILITY_WORKSPACES = [
	("enable_crm", "CRM"),
	("enable_buying", "Buying"),
	("enable_assets", "Assets"),
	("enable_projects", "Projects"),
	("enable_manufacturing", "Manufacturing"),
	("enable_quality", "Quality"),
	("enable_support", "Support"),
]


def _plain_user(roles):
	return "System Manager" not in roles


@frappe.whitelist()
def get_workspaces():
	"""Wraps solvronix_desk.api.get_workspaces: rail icons for the Retail Store app only."""
	from solvronix_desk.api import get_workspaces as original

	data = original()
	roles = set(frappe.get_roles())
	# an accountant keeps the Accounting app: that is their job, not a leak
	if not _plain_user(roles) or roles & {"Accounts User", "Accounts Manager"} or not isinstance(data, dict):
		return data
	for key in ("pages", "private_pages"):
		if data.get(key):
			data[key] = [p for p in data[key] if not p.get("app") or p.get("app") == APP]
	return data


def _trim_home_layout(data):
	"""The Retail Store home page is laid out from the workspace's `content` blocks. trim_workspace_page
	empties the shortcuts and cards a role may not open, but their blocks stay in the layout and leave
	holes. Drop those blocks too, so what is left flows together."""
	import json

	from retail_store.workspace_access import get_desktop_page

	for key in ("pages", "private_pages"):
		for page in data.get(key) or []:
			if page.get("name") != "Retail Store" or not page.get("content"):
				continue
			try:
				blocks = json.loads(page["content"])
				built = get_desktop_page(json.dumps({"name": "Retail Store"}))
			except Exception:
				continue
			shortcuts = {s.get("label") for s in (built.get("shortcuts") or {}).get("items") or []}
			cards = {c.get("label") for c in (built.get("cards") or {}).get("items") or []}
			kept, pending_header = [], None
			for b in blocks:
				d = b.get("data") or {}
				if b.get("type") == "header":
					pending_header = b
					continue
				if b.get("type") == "shortcut" and d.get("shortcut_name") not in shortcuts:
					continue
				if b.get("type") == "card" and d.get("card_name") not in cards:
					continue
				if pending_header:
					kept.append(pending_header)
					pending_header = None
				kept.append(b)
			page["content"] = json.dumps(kept)


def trim_workspace_page(result, user=None):
	"""get_desktop_page for the Retail Store home: the same role rules as the sidebar, so a cashier's
	home page does not offer Sales Invoice, Stock Entry or the item catalogue the sidebar hides."""
	roles = set(frappe.get_roles(user))
	# everyone but back office gets the same role rules as the sidebar (an accountant too: Retail Store
	# Settings and Staff Access are not theirs to open)
	if roles & BACK_OFFICE or not isinstance(result, dict):
		return result

	def visible(link_to):
		rule = LINKS.get(link_to)
		return not rule or bool(roles & rule[1])

	shortcuts = (result.get("shortcuts") or {}).get("items")
	if shortcuts is not None:
		result["shortcuts"]["items"] = [s for s in shortcuts if visible(s.get("link_to"))]
	cards = (result.get("cards") or {}).get("items")
	if cards is not None:
		kept = []
		for card in cards:
			card["links"] = [l for l in card.get("links") or [] if visible(l.get("link_to"))]
			if card["links"]:
				kept.append(card)
		result["cards"]["items"] = kept
	return result


def _link(label, link_type, link_to, icon="", child=1):
	return {
		"key": f"Link|{link_type}|{link_to}||",
		"label": label,
		"link_to": link_to,
		"link_type": link_type,
		"type": "Link",
		"icon": icon,
		"child": child,
		"collapsible": 0,
		"indent": 0,
		"keep_closed": 0,
		"url": None,
		"show_arrow": 0,
		"filters": None,
		"route_options": None,
		"tab": None,
		"open_in_new_tab": 0,
		"is_default_module": 0,
	}


def _trim(items, roles):
	out = []
	for it in items:
		rule = LINKS.get(it.get("link_to")) if it.get("type") == "Link" else None
		if rule:
			label, allowed = rule
			if not (roles & BACK_OFFICE or roles & allowed):
				continue
			it = {**it, "label": label}
		elif it.get("type") == "Section Break":
			it = {**it, "label": SECTIONS.get(it.get("label"), it.get("label"))}
		out.append(it)
	# a section whose links were all removed disappears with them
	kept = []
	for i, it in enumerate(out):
		if it.get("type") == "Section Break":
			following = out[i + 1 :]
			children = []
			for nxt in following:
				if nxt.get("type") == "Section Break" or not cint(nxt.get("child")):
					break
				children.append(nxt)
			if not children:
				continue
		kept.append(it)
	return kept


def _people(roles):
	from frappe import has_permission

	rows = []
	if "hrms" in frappe.get_installed_apps() and cint(frappe.db.get_single_value("Retail Store Settings", "enable_hr")):
		if roles & (BACK_OFFICE | STAFF):
			rows.append(_link("Clock In / Out", "Page", "store-clock"))
		for doctype, label, allowed in PEOPLE:
			if (roles & BACK_OFFICE or roles & allowed) and has_permission(doctype, "read"):
				rows.append(_link(label, "DocType", doctype))
	if not rows:
		return []
	if len(rows) == 1:  # shop floor: just the clock, no section around it
		return [{**rows[0], "child": 0, "icon": "clock"}]
	return [
		{**_link("People", "Section Break", ""), "type": "Section Break", "key": "Section Break|People", "child": 0, "collapsible": 1, "indent": 1, "icon": "users", "link_to": None, "link_type": None},
		*rows,
	]


def _back_office(roles):
	if not roles & BACK_OFFICE:
		return []
	rows = [
		_link(label, "DocType", doctype)
		for doctype, label in BACK_OFFICE_LINKS
		if frappe.db.exists("DocType", doctype) and frappe.has_permission(doctype, "read")
	]
	for report, label in BACK_OFFICE_REPORTS:
		if frappe.db.exists("Report", report) and frappe.get_doc("Report", report).is_permitted():
			row = _link(label, "Report", report)
			row["report"] = {"report_type": "Script Report", "ref_doctype": "GL Entry"}
			rows.append(row)
	if not rows:
		return []
	return [
		{**_link("Back Office", "Section Break", ""), "type": "Section Break", "key": "Section Break|Back Office", "child": 0, "collapsible": 1, "indent": 1, "icon": "briefcase", "link_to": None, "link_type": None},
		*rows,
	]


def _addons(roles):
	if "Store Owner" not in roles:
		return []
	settings = frappe.get_cached_doc("Retail Store Settings")
	rows = [
		_link(workspace, "Workspace", workspace)
		for flag, workspace in CAPABILITY_WORKSPACES
		if cint(settings.get(flag)) and frappe.db.exists("Workspace", workspace)
	]
	if not rows:
		return []
	return [
		{**_link("Add-ons", "Section Break", ""), "type": "Section Break", "key": "Section Break|Add-ons", "child": 0, "collapsible": 1, "indent": 1, "icon": "layout-grid", "link_to": None, "link_type": None},
		*rows,
	]


@frappe.whitelist()
def get_versions():
	"""Wraps frappe.utils.change_log.get_versions (the About dialog and the "Installed Apps" list in the
	avatar menu): app names and version numbers are for System Manager, not for shop staff."""
	from frappe.utils.change_log import get_versions as original

	if "System Manager" in frappe.get_roles():
		return original()
	return {}


def boot_session(bootinfo):
	user = frappe.session.user
	if user == "Guest":
		return
	if user == "Administrator":
		bootinfo.retail_store_pos_form_view = True
		return
	roles = set(frappe.get_roles(user))
	bootinfo.retail_store_pos_form_view = bool(roles & (BACK_OFFICE | {"Store Manager"}))
	if not _plain_user(roles):
		return
	if not roles & BACK_OFFICE and isinstance(bootinfo.get("workspaces"), dict):
		_trim_home_layout(bootinfo.workspaces)  # the desk draws the home page from boot, not from get_workspaces
	sidebar = (bootinfo.get("module_sidebars") or {}).get("Retail Store")
	if not sidebar:
		return
	items = _trim(sidebar.get("items") or [], roles)
	if roles & {"Store Attendant", "Warehouse Attendant", "Stock Receiver"} and not roles & {"Store Manager", "Warehouse Manager"}:
		# the plain "Request Stock" screen stands in for the Material Request / Stock Entry forms
		at = next((i + 1 for i, it in enumerate(items) if it.get("link_to") == "Stock Balance"), None)
		if at is not None:
			items.insert(at, _link("Request Stock", "Page", "stock-request"))
	# People goes after the stock / catalogue / till sections, before Setup
	setup_at = next((i for i, it in enumerate(items) if it.get("label") == "Setup"), len(items))
	sidebar["items"] = items[:setup_at] + _people(roles) + _back_office(roles) + _addons(roles) + items[setup_at:]

	_pin_to_retail_shell(bootinfo, sidebar["items"])


def _pin_to_retail_shell(bootinfo, items):
	"""Frappe opens a doctype in the module shell that claims it (Sales Invoice -> Accounts,
	Employee -> HR Setup...), which swaps the Retail Store sidebar for an ERPNext / Frappe HR one.
	Anything the Retail Store sidebar itself links to opens inside Retail Store instead."""
	shells = bootinfo.get("canonical_shell")
	if not isinstance(shells, dict):
		return
	for it in items:
		if it.get("type") != "Link" or it.get("link_type") not in ("DocType", "Report", "Page"):
			continue
		shells.setdefault(it["link_type"], {})[it["link_to"]] = "Retail Store"
		if it["link_type"] == "DocType" and isinstance(bootinfo.get("entity_module"), dict):
			bootinfo.entity_module.pop(it["link_to"], None)
