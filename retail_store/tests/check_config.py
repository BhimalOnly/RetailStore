"""Server-side checks for toggles, branding and navigation.

Run: bench --site <site> execute retail_store.tests.check_config.run
Restores every setting it changes.
"""

import frappe

results = []


def check(name, ok, detail=""):
	results.append((name, bool(ok)))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def _dock(app="erpnext"):
	from frappe.desk.doctype.dock.dock import resolve_app_dock

	return {e["link_to"]: int(e.get("hidden") or 0) for e in resolve_app_dock(app, upto="site", gated=False)}


def run():
	frappe.set_user("Administrator")
	s = frappe.get_doc("Retail Store Settings")
	original = s.as_dict()

	# --- defaults
	dock = _dock()
	check("Core modules visible in dock", all(dock.get(m) == 0 for m in ("Accounts", "Selling", "Stock")), dock)
	check("Optional modules hidden by default", all(dock.get(m) == 1 for m in ("CRM", "Buying", "Manufacturing", "Quality", "Support", "Assets", "Projects")), dock)
	check("Loyalty on by default", s.enable_loyalty and s.default_loyalty_program == "Retail Rewards")

	# --- CRM toggle on/off
	s.enable_crm = 1
	s.save()
	check("CRM toggle shows CRM in dock", _dock().get("CRM") == 0)
	check("CRM toggle grants Store Owner Lead access", frappe.db.exists("Custom DocPerm", {"parent": "Lead", "role": "Store Owner"}))
	blocked = frappe.get_all("Block Module", filters={"parent": "Retail Store Staff"}, pluck="module")
	check("CRM unblocked for retail staff", "CRM" not in blocked, blocked)
	check(
		"Cashier user's blocked modules updated",
		"CRM" not in frappe.get_all("Block Module", filters={"parent": "cashier.downtown@demo.example"}, pluck="module"),
	)
	s.enable_crm = 0
	s.save()
	check("CRM toggle off hides it again", _dock().get("CRM") == 1)
	check("CRM toggle off revokes Store Owner grant", not frappe.db.exists("Custom DocPerm", {"parent": "Lead", "role": "Store Owner"}))

	# --- e-commerce needs webshop
	s.enable_ecommerce = 1
	try:
		s.save()
		check("E-commerce toggle refuses without webshop app", "webshop" in frappe.get_installed_apps())
	except frappe.ValidationError as e:
		check("E-commerce toggle refuses without webshop app", "webshop" in str(e))
	s.reload()

	# --- loyalty toggle
	s.enable_loyalty = 0
	s.save()
	check("Loyalty off ends the program", frappe.db.get_value("Loyalty Program", "Retail Rewards", "to_date") is not None)
	s.enable_loyalty = 1
	s.save()
	check("Loyalty on re-opens the program", frappe.db.get_value("Loyalty Program", "Retail Rewards", "to_date") is None)

	# --- branding is per-site data
	s.brand_name = "Acme Shoes"
	s.brand_color = "#AA0055"
	s.brand_logo = "/files/acme.png"
	s.save()
	from retail_store.branding import get_branding

	b = get_branding()
	check("Branding read from per-site settings", b["brand_name"] == "Acme Shoes" and b["brand_color"] == "#AA0055")
	check("Logo pushed to Navbar Settings", frappe.db.get_single_value("Navbar Settings", "app_logo") == "/files/acme.png")
	check("Brand name pushed to Website Settings", frappe.db.get_single_value("Website Settings", "app_name") == "Acme Shoes")

	# --- navigation for a cashier
	frappe.set_user("cashier.downtown@demo.example")
	user = frappe.get_doc("User", "cashier.downtown@demo.example")
	check("Retail staff land in Retail Store app", user.get("default_app") == "retail_store", user.get("default_app"))
	from retail_store.branding import has_app_permission

	check("Retail Store app tile permitted for cashier", has_app_permission())
	from frappe.utils.modules import is_module_visible

	check("Manufacturing hidden for cashier", not is_module_visible("Manufacturing"))
	check("Stock visible for cashier", is_module_visible("Stock"))
	frappe.set_user("Administrator")

	# --- restore
	s.reload()
	for f in ("brand_name", "brand_color", "brand_logo", "enable_crm", "enable_ecommerce", "enable_loyalty"):
		s.set(f, original.get(f))
	s.save()
	frappe.db.commit()

	failed = [r for r in results if not r[1]]
	print(f"\n{len(results) - len(failed)}/{len(results)} config checks passed")
