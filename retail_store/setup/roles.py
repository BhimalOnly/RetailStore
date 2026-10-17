"""Custom retail roles and their default Role Permissions.

Roles are COMBINABLE: a person can hold Store Attendant + Store Cashier, or
Warehouse Manager + Store Manager, and simply gets the union of rights. Nothing
in this app assumes one role per person. All standard ERPNext roles are kept;
accounting uses the stock "Accounts Manager" role unchanged.

Permissions are written as Custom DocPerm rows (what Role Permissions Manager
edits), so they can be adjusted per client in the UI afterwards. Re-running
setup only ADDS rights listed here; it never removes a right someone granted
by hand. To reset a doctype to this baseline use Role Permissions Manager >
"Reset to defaults" and then `bench --site <site> migrate`.

Codes: r read, w write, c create, d delete, s submit, x cancel, a amend,
p print, e email, rep report, exp export, sh share.
"""

import frappe

ROLES = {
	"Store Attendant": "Shop-floor staff: helps customers, creates customers, drafts sales, requests stock.",
	"Store Cashier": "Runs the till: POS sales, payments, opening/closing the register.",
	"Store Manager": "Runs a store: approves requests, transfers and counts stock, cancels/amends sales.",
	"Warehouse Attendant": "Picks/packs and counts stock, requests stock; cannot post transfers.",
	"Warehouse Manager": "Runs a warehouse: approves requests, posts transfers, maintains the catalogue.",
	"Store Owner": "Sees and does everything retail across all locations, including bulk transfers.",
	"Store Admin": "Configures the store system: locations, staff access, POS profiles, catalogue, branding.",
}

ALL = list(ROLES)

# Extra rights the Store Owner can hand to individual staff (Retail Store Settings > Stock Transfers >
# Extra Staff Permissions). Never given by default and not part of ALL: staff_grants.py adds and
# removes them from the people listed there.
GRANT_ROLES = {
	"Stock Receiver": "Can book stock into their own location (deliveries, transfers arriving).",
	"Price Editor": "Can change selling prices in the price list.",
}
MANAGERS = ["Store Manager", "Warehouse Manager", "Store Owner"]

READ = "r rep p"
REF = "r"  # link targets that only need to be readable/selectable

# Master data every retail role must be able to read to use the forms at all.
_BASE_READ = {
	"Item": READ,
	"Item Group": REF,
	"Item Attribute": REF,
	"Item Price": REF,
	"Price List": REF,
	"UOM": REF,
	"Brand": REF,
	"Warehouse": REF,
	"Customer Group": REF,
	"Territory": REF,
	"Company": REF,
	"Currency": REF,
	"Mode of Payment": REF,
	"Loyalty Program": REF,
	"Stock Settings": REF,  # every Stock Entry / Material Request form reads it on open
	"Bin": READ,
	"Stock Ledger Entry": READ,  # Stock Balance / Stock Ledger reports
	"Batch": REF,
	"Serial No": REF,
	"Stock Entry Type": REF,
	"Sales Taxes and Charges Template": REF,
	"Item Tax Template": REF,
	"Cost Center": REF,
	"Custom HTML Block": REF,  # the Retail Store home greeting (home.py); a role without it gets no block
	"Number Card": REF,  # Sales today / Requests waiting on the home page
}

_CUSTOMER = {"Customer": "r w c rep p e", "Contact": "r w c", "Address": "r w c"}
_REQUEST = {"Material Request": "r w c rep p"}  # submit is done by approvers via workflow
_TILL = {
	"Sales Invoice": "r w c s rep p e",
	"POS Invoice": "r w c s rep p e",
	"POS Opening Entry": "r w c s",
	"POS Closing Entry": "r w c s rep p",
	"POS Profile": REF,
	"POS Settings": REF,
	"Stock Settings": REF,  # POS reads allow_negative_stock on load (v16 pos_controller.js)
	"Payment Entry": "r w c s rep p e",
	"Loyalty Point Entry": READ,
	"Coupon Code": REF,
	"Pricing Rule": REF,
	# SELECT only: Sales Invoice / POS validation must resolve the income & receivable
	# accounts, but till staff must not READ (browse) the chart of accounts.
	"Account": "sel",
}
_STOCK_POSTING = {
	"Stock Entry": "r w c s x a rep p e",
	"Material Request": "r w c s x a rep p e",
	"Stock Reconciliation": "r w c s x a rep p",
	"Delivery Note": "r w c s x a rep p e",
	"Batch": "r w c",
	"Serial No": "r w",
}
_CATALOGUE = {
	"Item": "r w c rep p exp",
	"Item Group": "r w c",
	"Item Attribute": "r w c",
	"Item Price": "r w c d rep",
	"Price List": "r w c",
	"Brand": "r w c",
	"UOM": "r w c",
}


_RECEIVER = {"Stock Entry": "r w c s rep p", "Stock Entry Type": REF}
_PRICE_EDITOR = {"Item Price": "r w c rep"}


def _merge(*maps):
	out = {}
	for m in maps:
		for dt, codes in m.items():
			out[dt] = " ".join(sorted(set(out.get(dt, "").split()) | set(codes.split())))
	return out


PERMISSIONS = {
	"Stock Receiver": _merge(_BASE_READ, _RECEIVER),
	"Price Editor": _merge(_BASE_READ, _PRICE_EDITOR),
	"Store Attendant": _merge(
		_BASE_READ,
		_CUSTOMER,
		_REQUEST,
		{"Sales Invoice": "r w c rep p", "Stock Entry": READ, "Delivery Note": READ},
	),
	"Store Cashier": _merge(_BASE_READ, _CUSTOMER, _REQUEST, _TILL, {"Stock Entry": READ}),
	"Store Manager": _merge(
		_BASE_READ,
		_CUSTOMER,
		_TILL,
		_STOCK_POSTING,
		{
			"Sales Invoice": "r w c s x a rep p e exp",
			"POS Invoice": "r w c s x a rep p e exp",
			"POS Closing Entry": "r w c s x a rep p",
			"POS Profile": "r w",
			"Item Price": "r w c rep",
			"Sales Order": "r w c s x a rep p e",
			"Quotation": "r w c s rep p e",
			"Pricing Rule": "r w c",
			"Coupon Code": "r w c",
			"Payment Entry": "r w c s x a rep p e",
		},
	),
	"Warehouse Attendant": _merge(
		_BASE_READ,
		_REQUEST,
		{
			"Stock Entry": READ,
			"Stock Reconciliation": "r w c rep p",  # count sheets; a manager submits
			"Delivery Note": READ,
			"Pick List": "r w c rep p",
		},
	),
	"Warehouse Manager": _merge(
		_BASE_READ,
		_STOCK_POSTING,
		_CATALOGUE,
		{"Pick List": "r w c s x a rep p", "Item Attribute": "r w c", "Warehouse": "r rep"},
	),
	"Store Owner": _merge(
		_BASE_READ,
		_CUSTOMER,
		_TILL,
		_STOCK_POSTING,
		_CATALOGUE,
		{
			"Account": REF,  # owners may see the chart of accounts; till staff may not
			"GL Entry": "r rep",  # Profit and Loss / Balance Sheet read the ledger
			"Fiscal Year": REF,
			"Customer": "r w c d rep p e exp",
			"Sales Invoice": "r w c s x a rep p e exp",
			"POS Invoice": "r w c s x a rep p e exp",
			"POS Closing Entry": "r w c s x a rep p",
			"POS Profile": "r w c d",
			"POS Settings": "r w",
			"Sales Order": "r w c s x a rep p e exp",
			"Quotation": "r w c s x a rep p e",
			"Payment Entry": "r w c s x a rep p e exp",
			"Pricing Rule": "r w c d",
			"Coupon Code": "r w c d",
			"Loyalty Program": "r w c",
			"Loyalty Point Entry": "r rep exp",
			"Warehouse": "r w c rep",
			"Item": "r w c d rep p exp",
			"Pick List": "r w c s x a rep p",
			"Stock Entry": "r w c s x a d rep p e exp",
			"Material Request": "r w c s x a d rep p e exp",
		},
	),
	"Store Admin": _merge(
		_BASE_READ,
		_CATALOGUE,
		{
			"Customer": "r w c rep",
			"Warehouse": "r w c rep",
			"POS Profile": "r w c d",
			"POS Settings": "r w",
			"Loyalty Program": "r w c",
			"Mode of Payment": "r",
			"Stock Entry Type": "r",
			"User": "r",
		},
	),
}

# Reports and pages need the role listed on them too (stored as "Custom Role",
# so ERPNext's own report definitions stay untouched).
REPORT_ROLES = {
	"Stock Balance": ALL,
	"Stock Projected Qty": ALL,
	"Stock Ledger": MANAGERS + ["Store Admin", "Warehouse Attendant"],
	"Sales Register": ["Store Manager", "Store Owner"],
	"Sales Analytics": ["Store Manager", "Store Owner"],
	"Item-wise Sales Register": ["Store Manager", "Store Owner"],
	# the accounting roles are named so a Custom Role never narrows these two reports to the owner alone
	"Profit and Loss Statement": ["Store Owner", "Accounts User", "Accounts Manager", "Auditor"],
	"Balance Sheet": ["Store Owner", "Accounts User", "Accounts Manager", "Auditor"],
}
PAGE_ROLES = {
	"point-of-sale": ["Store Cashier", "Store Manager", "Store Owner"],
}

CODE_TO_FIELD = {
	"r": "read",
	"w": "write",
	"c": "create",
	"d": "delete",
	"s": "submit",
	"x": "cancel",
	"a": "amend",
	"p": "print",
	"e": "email",
	"rep": "report",
	"exp": "export",
	"sh": "share",
	"sel": "select",
}


def create_roles():
	for role, description in {**ROLES, **GRANT_ROLES}.items():
		if frappe.db.exists("Role", role):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role,
				"desk_access": 1,
				"description": description,
			}
		).insert(ignore_permissions=True)


# Till/floor staff may SELECT these (so links and validation resolve) but never READ them.
# apply_role_permissions only ever adds, so the read bit is cleared here on every run.
SELECT_ONLY = {
	"Store Cashier": ["Account"],
	"Store Manager": ["Account"],
}


def revoke_permissions():
	for role, doctypes in SELECT_ONLY.items():
		for doctype in doctypes:
			for name in frappe.get_all("Custom DocPerm", filters={"parent": doctype, "role": role}, pluck="name"):
				frappe.db.set_value("Custom DocPerm", name, {"read": 0, "select": 1})
			frappe.clear_cache(doctype=doctype)


def apply_role_permissions():
	from frappe.permissions import setup_custom_perms

	touched = set()
	for role, perms in PERMISSIONS.items():
		for doctype, codes in perms.items():
			if not frappe.db.exists("DocType", doctype):
				continue  # e.g. a doctype dropped in a future ERPNext version
			meta = frappe.get_meta(doctype)
			setup_custom_perms(doctype)
			name = frappe.db.get_value(
				"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
			)
			perm = (
				frappe.get_doc("Custom DocPerm", name)
				if name
				else frappe.get_doc({"doctype": "Custom DocPerm", "parent": doctype, "role": role, "permlevel": 0})
			)
			changed = perm.is_new()
			for code in codes.split():
				field = CODE_TO_FIELD[code]
				if field in ("submit", "cancel", "amend") and not meta.is_submittable:
					continue
				if not perm.get(field):
					perm.set(field, 1)
					changed = True
			if changed:
				perm.save(ignore_permissions=True)
				touched.add(doctype)

	for doctype in touched:
		frappe.clear_cache(doctype=doctype)


def apply_report_and_page_roles():
	for field, mapping in (("report", REPORT_ROLES), ("page", PAGE_ROLES)):
		doctype = "Report" if field == "report" else "Page"
		for target, roles in mapping.items():
			if not frappe.db.exists(doctype, target):
				continue
			name = frappe.db.get_value("Custom Role", {field: target})
			doc = (
				frappe.get_doc("Custom Role", name)
				if name
				else frappe.get_doc(
					{
						"doctype": "Custom Role",
						field: target,
						"ref_doctype": frappe.db.get_value("Report", target, "ref_doctype") if field == "report" else None,
					}
				)
			)
			if doc.is_new():
				# Start from the standard roles so we only ever add access.
				standard = frappe.get_all("Has Role", filters={"parenttype": doctype, "parent": target}, pluck="role")
				for r in standard:
					doc.append("roles", {"role": r})
			have = {r.role for r in doc.roles}
			for r in roles:
				if r not in have:
					doc.append("roles", {"role": r})
			doc.save(ignore_permissions=True)


# Retail Store Settings: operational settings (stock, access, loyalty, POS) are open to Store
# Owner / Store Admin at permlevel 0. Branding and the optional-module toggles (Capabilities) sit
# at permlevel 1, which only System Manager is granted: they change what the whole product shows
# and offers, so they are a configuration decision, not day-to-day operations.
SETTINGS_DOCTYPE = "Retail Store Settings"
SETTINGS_PERMISSIONS = {
	("System Manager", 0): {"read": 1, "write": 1, "create": 1, "print": 1, "email": 1, "share": 1},
	("System Manager", 1): {"read": 1, "write": 1},
	("System Manager", 2): {"read": 1, "write": 1},
	("Store Owner", 2): {"read": 1, "write": 1},
	("Store Admin", 0): {"read": 1, "write": 1, "create": 1},
	("Store Owner", 0): {"read": 1, "write": 1, "create": 1},
}


def apply_settings_permissions():
	"""Make Retail Store Settings' Custom DocPerm rows exactly SETTINGS_PERMISSIONS.

	Custom DocPerm rows replace the doctype's standard ones entirely, and they exist on this
	doctype, so the JSON alone is not enough. Extra rows (e.g. a permlevel-1 grant to anyone
	else, made in Role Permission Manager) are removed."""
	_apply_exact_permissions(SETTINGS_DOCTYPE, SETTINGS_PERMISSIONS)


# Workspaces are shared product scaffolding, identical on every client site: only System Manager
# changes them. Frappe's own rows let every Desk User create, change and delete workspaces (their
# private pages), which reaches the "+ New" menu entry and the API alike. Everyone keeps read.
WORKSPACE_DOCTYPE = "Workspace"
WORKSPACE_PERMISSIONS = {
	("System Manager", 0): {"read": 1, "write": 1, "create": 1, "delete": 1, "select": 1, "print": 1, "email": 1, "share": 1, "export": 1},
	("Workspace Manager", 0): {"read": 1, "write": 1, "create": 1, "delete": 1, "select": 1},
	("Desk User", 0): {"read": 1, "select": 1},
}
PERM_FIELDS = ("read", "write", "create", "delete", "select", "print", "email", "share", "export", "import", "report")


def apply_workspace_permissions():
	_apply_exact_permissions(WORKSPACE_DOCTYPE, WORKSPACE_PERMISSIONS, exact=True)


def _apply_exact_permissions(doctype, wanted, exact=False):
	from frappe.permissions import setup_custom_perms

	if not frappe.db.exists("DocType", doctype):
		return
	setup_custom_perms(doctype)
	have = {}
	for row in frappe.get_all(
		"Custom DocPerm", filters={"parent": doctype}, fields=["name", "role", "permlevel", "if_owner"]
	):
		if row.if_owner:
			frappe.delete_doc("Custom DocPerm", row.name, ignore_permissions=True, force=True)
			continue
		key = (row.role, row.permlevel)
		if key not in wanted or key in have:
			frappe.delete_doc("Custom DocPerm", row.name, ignore_permissions=True, force=True)
		else:
			have[key] = row.name
	for (role, level), flags in wanted.items():
		if (role, level) in have:
			doc = frappe.get_doc("Custom DocPerm", have[(role, level)])
		else:
			doc = frappe.get_doc({"doctype": "Custom DocPerm", "parent": doctype, "role": role, "permlevel": level})
		changed = doc.is_new()
		for field in PERM_FIELDS if exact else flags:
			value = flags.get(field, 0)
			if doc.get(field) != value:
				doc.set(field, value)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
	frappe.clear_cache(doctype=doctype)


def apply_portal_permissions():
	"""Portal ("Customer" role) users may read Customer; storefront.py confines it to their own.

	Needed by webshop's order page (see storefront.py). Only when webshop is installed."""
	from frappe.permissions import setup_custom_perms

	if "webshop" not in frappe.get_installed_apps() or not frappe.db.exists("Role", "Customer"):
		return
	setup_custom_perms("Customer")
	name = frappe.db.get_value("Custom DocPerm", {"parent": "Customer", "role": "Customer", "permlevel": 0, "if_owner": 0})
	if not name:
		frappe.get_doc({"doctype": "Custom DocPerm", "parent": "Customer", "role": "Customer", "permlevel": 0, "read": 1}).insert(
			ignore_permissions=True
		)
	frappe.clear_cache(doctype="Customer")


# Fields moved to permlevel 1 (setup/forms.py kind "restrict"): whoever can work with the document still READS them,
# only managers can WRITE them. Additive, like apply_role_permissions: nothing existing is removed or lowered, so Frappe's
# own level-1 rows (e.g. "All" read on Sales Invoice / POS Invoice) are left exactly as they are.
LEVEL1_DOCTYPES = ("Customer", "Sales Order", "Sales Invoice", "POS Invoice", "POS Profile")
# ...except these: the fields are the managers' alone, so no one else is given level-1 read (till policy toggles on POS Profile)
LEVEL1_MANAGERS_ONLY = ("POS Profile",)
LEVEL1_WRITERS = ("Store Manager", "Store Owner", "Store Admin")


def apply_level1_permissions():
	from frappe.permissions import setup_custom_perms

	for doctype in LEVEL1_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		rows = frappe.get_all("Custom DocPerm", filters={"parent": doctype, "permlevel": 1}, fields=["role", "read", "if_owner"])
		everyone_reads = any(r.role == "All" and r.read and not r.if_owner for r in rows)
		wanted = {role: {"read": 1, "write": 1} for role in LEVEL1_WRITERS}
		if not everyone_reads and doctype not in LEVEL1_MANAGERS_ONLY:
			for role, perms in PERMISSIONS.items():
				if role in ALL and "r" in perms.get(doctype, "").split():
					wanted.setdefault(role, {"read": 1})
		for role, flags in wanted.items():
			name = frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 1, "if_owner": 0})
			perm = frappe.get_doc("Custom DocPerm", name) if name else frappe.get_doc({"doctype": "Custom DocPerm", "parent": doctype, "role": role, "permlevel": 1})
			changed = perm.is_new()
			for field in flags:
				if not perm.get(field):
					perm.set(field, 1)
					changed = True
			if changed:
				perm.save(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)


def setup_roles_and_permissions():
	create_roles()
	apply_role_permissions()
	apply_level1_permissions()
	apply_settings_permissions()
	apply_workspace_permissions()
	apply_portal_permissions()
	revoke_permissions()
	apply_report_and_page_roles()
