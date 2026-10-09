"""Optional capabilities: present in the app, hidden unless a client needs them.

Native levers, all reversible:
1. Module Profile "Retail Store Staff" blocks disabled modules for every user
   holding a retail role (navigation only, per Frappe's design).
2. The disabled modules are hidden site-wide from ERPNext's Dock (v16 "Apps"
   navigation) via the Dock's site layer, and from Desktop Icons (v16
   "Desktop" navigation, if a site switches to it).
3. Store Owner is granted the module's main doctypes only while it is enabled.

Core modules (Stock, Selling, Accounts, POS) are never touched.
"""

import frappe

from retail_store.setup.roles import ROLES

MODULE_PROFILE = "Retail Store Staff"
OWNER = "Store Owner"

FULL = {"read": 1, "write": 1, "create": 1, "report": 1, "print": 1, "email": 1, "export": 1}
SUBMIT = {**FULL, "submit": 1, "cancel": 1, "amend": 1}

OPTIONAL = {
	"enable_crm": {
		"modules": ["CRM"],
		"icons": ["CRM"],
		"grants": {"Lead": FULL, "Opportunity": FULL, "Prospect": FULL, "Campaign": FULL},
	},
	"enable_ecommerce": {
		"modules": ["Webshop"],
		"icons": ["Webshop"],
		"grants": {"Website Item": FULL},
	},
	"enable_buying": {
		"modules": ["Buying"],
		"icons": ["Buying"],
		"grants": {
			"Supplier": FULL,
			"Purchase Order": SUBMIT,
			"Purchase Receipt": SUBMIT,
			"Purchase Invoice": SUBMIT,
			"Supplier Quotation": SUBMIT,
			"Request for Quotation": SUBMIT,
		},
	},
	"enable_hr": {"modules": ["HR", "Payroll"], "icons": ["HR", "Payroll", "Frappe HR"], "grants": {}},
	"enable_manufacturing": {"modules": ["Manufacturing"], "icons": ["Manufacturing"], "grants": {}},
	"enable_quality": {"modules": ["Quality Management"], "icons": ["Quality"], "grants": {}},
	"enable_support": {"modules": ["Support"], "icons": ["Support"], "grants": {}},
	"enable_assets": {"modules": ["Assets"], "icons": ["Assets"], "grants": {}},
	"enable_projects": {"modules": ["Projects"], "icons": ["Projects"], "grants": {}},
}

# Not retail, never offered as a toggle; blocked for retail staff only.
ALWAYS_BLOCKED_FOR_STAFF = ["Subcontracting", "Maintenance"]


def _existing_modules(modules):
	return [m for m in modules if frappe.db.exists("Module Def", m)]


def apply_capabilities(settings=None):
	settings = settings or frappe.get_single("Retail Store Settings")
	blocked = list(_existing_modules(ALWAYS_BLOCKED_FOR_STAFF))
	dock_visibility = {}

	for field, cfg in OPTIONAL.items():
		enabled = bool(settings.get(field))
		if not enabled:
			blocked += _existing_modules(cfg["modules"])
		_set_icons_hidden(cfg["icons"], hidden=not enabled)
		_set_owner_grants(cfg["grants"], enabled)
		for label in cfg["icons"]:
			dock_visibility[label] = not enabled

	_set_dock_hidden(dock_visibility)

	if settings.get("enable_ecommerce") and "webshop" in frappe.get_installed_apps():
		frappe.db.set_single_value("Webshop Settings", "enabled", 1)

	_sync_module_profile(sorted(set(blocked)))
	from retail_store.workspace_access import apply_workspace_access

	apply_workspace_access()
	from retail_store.workspace_access import backfill_default_landing

	backfill_default_landing()
	frappe.cache.delete_value("desktop_icons")


def _set_icons_hidden(labels, hidden):
	for name in frappe.get_all("Desktop Icon", filters={"label": ["in", labels]}, pluck="name"):
		frappe.db.set_value("Desktop Icon", name, "hidden", int(hidden), update_modified=False)


def _set_dock_hidden(hidden_by_sidebar):
	"""Write ERPNext's site-layer Dock with our optional modules shown/hidden.

	Only rows for sidebars we manage change; anything a Workspace Manager arranged
	stays as it was."""
	try:
		from frappe.desk.doctype.dock.dock import _save_layer, resolve_app_dock
	except ImportError:
		return  # older v16 builds without the per-app Dock

	for app in ("erpnext", "hrms", "webshop"):
		if app not in frappe.get_installed_apps():
			continue
		entries = resolve_app_dock(app, upto="site", gated=False)
		changed = False
		for e in entries:
			if e.get("link_to") in hidden_by_sidebar:
				want = int(hidden_by_sidebar[e["link_to"]])
				if int(e.get("hidden") or 0) != want:
					e["hidden"] = want
					changed = True
		if changed:
			_save_layer(app, entries, user=None, require_visible=False)


def _set_owner_grants(grants, enabled):
	from frappe.permissions import setup_custom_perms

	for doctype, rights in grants.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		name = frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": OWNER, "permlevel": 0, "if_owner": 0})
		if enabled and not name:
			setup_custom_perms(doctype)
			submittable = frappe.get_meta(doctype).is_submittable
			perm = {k: v for k, v in rights.items() if submittable or k not in ("submit", "cancel", "amend")}
			frappe.get_doc({"doctype": "Custom DocPerm", "parent": doctype, "role": OWNER, "permlevel": 0, **perm}).insert(
				ignore_permissions=True
			)
			frappe.clear_cache(doctype=doctype)
		elif not enabled and name:
			frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)
			frappe.clear_cache(doctype=doctype)


def _sync_module_profile(blocked):
	if not frappe.db.exists("Module Profile", MODULE_PROFILE):
		frappe.get_doc(
			{
				"doctype": "Module Profile",
				"module_profile_name": MODULE_PROFILE,
				"block_modules": [{"module": m} for m in blocked],
			}
		).insert(ignore_permissions=True)
	else:
		current = frappe.get_all(
			"Block Module", filters={"parent": MODULE_PROFILE, "parenttype": "Module Profile"}, pluck="module"
		)
		if set(current) != set(blocked):
			# Write the rows directly: Module Profile.save() queues update_all_users and
			# locks the document, so a second toggle in the same request would fail.
			# Users are synced below instead (that job also skips users blocking nothing).
			frappe.db.delete("Block Module", {"parent": MODULE_PROFILE, "parenttype": "Module Profile"})
			for idx, module in enumerate(blocked, start=1):
				frappe.get_doc(
					{
						"doctype": "Block Module",
						"parent": MODULE_PROFILE,
						"parenttype": "Module Profile",
						"parentfield": "block_modules",
						"module": module,
						"idx": idx,
					}
				).db_insert()
			frappe.clear_document_cache("Module Profile", MODULE_PROFILE)

	for user in frappe.get_all("User", filters={"module_profile": MODULE_PROFILE}, pluck="name"):
		apply_module_profile(user)


def apply_module_profile(user):
	"""Give a retail user the retail navigation (blocked modules + land in the
	Retail Store app). System Managers keep the full desk."""
	roles = set(frappe.get_roles(user))
	if user in ("Administrator", "Guest") or "System Manager" in roles or not roles & set(ROLES):
		return
	doc = frappe.get_doc("User", user)
	blocked = frappe.get_all("Block Module", filters={"parent": MODULE_PROFILE, "parenttype": "Module Profile"}, pluck="module")
	wants_default_app = doc.meta.has_field("default_app") and not doc.get("default_app")
	if (
		doc.module_profile == MODULE_PROFILE
		and {d.module for d in doc.block_modules} == set(blocked)
		and not wants_default_app
	):
		return
	if wants_default_app:
		doc.default_app = "retail_store"
	doc.module_profile = MODULE_PROFILE
	doc.set("block_modules", [{"module": m} for m in blocked])
	doc.flags.ignore_permissions = True
	doc.save()
