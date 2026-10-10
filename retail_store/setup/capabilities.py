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
# Lookup masters a form links to (Opportunity Type, Sales Stage...): without read, saving the
# main document fails with a 403 on a harmless dropdown. tests/capability_links.py lists them.
LOOKUP = {"read": 1}

OPTIONAL = {
	"enable_crm": {
		"modules": ["CRM"],
		"icons": ["CRM"],
		"grants": {
			"Lead": FULL,
			"Opportunity": FULL,
			"Prospect": FULL,
			"Campaign": FULL,
			"Opportunity Type": LOOKUP,
			"Sales Stage": LOOKUP,
			"Opportunity Lost Reason": LOOKUP,
			"Competitor": LOOKUP,
			"Industry Type": LOOKUP,
			"Market Segment": LOOKUP,
		},
	},
	"enable_ecommerce": {
		"modules": ["Webshop"],
		"icons": ["Webshop"],
		"grants": {"Website Item": FULL, "Website Slideshow": FULL},
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
		setup_webshop_defaults()

	from retail_store.portal_access import apply_portal_menu

	apply_portal_menu()

	_sync_module_profile(sorted(set(blocked)))
	from retail_store.workspace_access import apply_workspace_access

	apply_workspace_access()
	from retail_store.workspace_access import backfill_default_landing

	backfill_default_landing()
	frappe.cache.delete_value("desktop_icons")


OFFLINE_GATEWAY = "Pay in Store or on Delivery"


def setup_webshop_defaults():
	"""First-time storefront defaults. Each part runs only while its setting is still blank, so a
	client's own choices (a real price list, a real payment gateway) are never overwritten.

	A fresh Webshop Settings shows no prices, no stock and no variant picker, which is a blank
	shop; and without a Payment Gateway Account the cart can only "Request for Quote" (Webshop
	silently switches checkout off). So we also provide an OFFLINE gateway, "Pay in Store or on
	Delivery", pointing at the company's cash account: "Place Order" then creates a Sales Order
	and payment is taken in person. Switch to a real gateway per client (README)."""
	ws = frappe.get_single("Webshop Settings")
	company = ws.company or frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	changed = False
	if not ws.price_list:
		price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1, "name": "Standard Selling"}) or frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1}
		)
		if price_list:
			ws.company = company
			ws.price_list = price_list
			ws.default_customer_group = ws.default_customer_group or frappe.db.get_single_value("Selling Settings", "customer_group")
			ws.show_price = 1
			ws.show_stock_availability = 1
			ws.enable_variants = 1
			changed = True
	if not ws.payment_gateway_account and company:
		account = _ensure_offline_gateway_account(company)
		if account:
			ws.payment_gateway_account = account
			ws.enable_checkout = 1
			changed = True
	# Guests who press Add to Cart go to the SHOPPER login (/account/login), not Solvronix's staff /login
	if not ws.redirect_on_action:
		ws.redirect_on_action = "/account/login"
		changed = True
	if changed:
		ws.flags.ignore_permissions = True
		ws.save()
	# People who sign up themselves get NO roles unless Portal Settings names a default one, and the
	# "Customer" role is what lets them read their own Customer record (without it their own order
	# confirmation page says "Not Permitted" and the portal sidebar is empty). Only while blank.
	if frappe.db.exists("Role", "Customer") and not frappe.db.get_single_value("Portal Settings", "default_role"):
		frappe.db.set_single_value("Portal Settings", "default_role", "Customer")
	# The public home page is the store front page (banner, categories, new arrivals), not the login
	# screen (only while no home page is chosen; "all-products" stays available as a choice)
	if not frappe.db.get_single_value("Website Settings", "home_page"):
		frappe.db.set_single_value("Website Settings", "home_page", "store-home")


def _ensure_offline_gateway_account(company):
	if "payments" not in frappe.get_installed_apps():
		return None
	cash = frappe.db.get_value("Company", company, "default_cash_account")
	currency = frappe.db.get_value("Company", company, "default_currency")
	if not (cash and currency):
		return None
	if not frappe.db.exists("Payment Gateway", OFFLINE_GATEWAY):
		frappe.get_doc({"doctype": "Payment Gateway", "gateway": OFFLINE_GATEWAY}).insert(ignore_permissions=True)
	name = frappe.db.get_value("Payment Gateway Account", {"payment_gateway": OFFLINE_GATEWAY, "company": company})
	if name:
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "Payment Gateway Account",
				"payment_gateway": OFFLINE_GATEWAY,
				"payment_channel": "Other",
				"company": company,
				"payment_account": cash,
				"currency": currency,
				"is_default": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


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


def _write_profile(name, blocked):
	"""Create or update a Module Profile so it blocks exactly `blocked`."""
	if not frappe.db.exists("Module Profile", name):
		frappe.get_doc(
			{
				"doctype": "Module Profile",
				"module_profile_name": name,
				"block_modules": [{"module": m} for m in blocked],
			}
		).insert(ignore_permissions=True)
		return
	current = frappe.get_all("Block Module", filters={"parent": name, "parenttype": "Module Profile"}, pluck="module")
	if set(current) != set(blocked):
		# Write the rows directly: Module Profile.save() queues update_all_users and
		# locks the document, so a second toggle in the same request would fail.
		# Users are synced by apply_module_profile instead.
		frappe.db.delete("Block Module", {"parent": name, "parenttype": "Module Profile"})
		for idx, module in enumerate(blocked, start=1):
			frappe.get_doc(
				{
					"doctype": "Block Module",
					"parent": name,
					"parenttype": "Module Profile",
					"parentfield": "block_modules",
					"module": module,
					"idx": idx,
				}
			).db_insert()
		frappe.clear_document_cache("Module Profile", name)


def _sync_module_profile(blocked):
	_write_profile(MODULE_PROFILE, blocked)
	# Variants for users who also lose Accounts / Selling / Stock (see _role_gated_modules).
	for variant in frappe.get_all("Module Profile", filters={"name": ["like", f"{MODULE_PROFILE} - %"]}, pluck="name"):
		gated = variant[len(MODULE_PROFILE) + 3 :].split("/")
		_write_profile(variant, sorted(set(blocked) | set(gated)))

	for user in frappe.get_all("User", filters={"module_profile": ["like", f"{MODULE_PROFILE}%"]}, pluck="name"):
		apply_module_profile(user)


# Core modules whose rail buttons (and workspaces) only back-office users may use. A retail
# user who lacks BOTH a back-office role and the module's native ERPNext role gets the module
# blocked, so the Dock never shows a button that answers "Not permitted". Same role lists as
# workspace_access, so navigation and enforcement cannot drift apart.
# Module -> the workspace whose role list decides who may use it.
GATED_MODULES = {
	"Accounts": "Accounting",
	"Selling": "Selling",
	"Stock": "Stock",
	"CRM": "CRM",
	"Buying": "Buying",
	"Assets": "Assets",
	"Projects": "Projects",
	"Manufacturing": "Manufacturing",
	"Quality Management": "Quality",
	"Support": "Support",
}


def _role_gated_modules(roles):
	from retail_store.workspace_access import allowed_roles_for

	return [m for m, ws in GATED_MODULES.items() if not set(roles) & set(allowed_roles_for(ws) or [])]


def apply_module_profile(user):
	"""Give a retail user the retail navigation (blocked modules + land in the
	Retail Store app). System Managers keep the full desk. Core modules the user's roles
	cannot open (Accounts / Selling / Stock) are blocked too, via a profile variant."""
	roles = set(frappe.get_roles(user))
	if user in ("Administrator", "Guest") or "System Manager" in roles or not roles & set(ROLES):
		return
	doc = frappe.get_doc("User", user)
	base = frappe.get_all("Block Module", filters={"parent": MODULE_PROFILE, "parenttype": "Module Profile"}, pluck="module")
	gated = _role_gated_modules(roles)
	profile = MODULE_PROFILE if not gated else f"{MODULE_PROFILE} - {'/'.join(gated)}"
	blocked = sorted(set(base) | set(gated))
	_write_profile(profile, blocked)
	wants_default_app = doc.meta.has_field("default_app") and not doc.get("default_app")
	if (
		doc.module_profile == profile
		and {d.module for d in doc.block_modules} == set(blocked)
		and not wants_default_app
	):
		return
	if wants_default_app:
		doc.default_app = "retail_store"
	doc.module_profile = profile
	doc.set("block_modules", [{"module": m} for m in blocked])
	doc.flags.ignore_permissions = True
	doc.save()
