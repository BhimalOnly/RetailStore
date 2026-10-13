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
	# Pin the baseline: the site may have capabilities switched on (e.g. CRM). Originals are
	# restored at the end.
	for f in ("enable_crm", "enable_buying", "enable_hr", "enable_manufacturing", "enable_quality", "enable_support", "enable_assets", "enable_projects"):
		s.set(f, 0)
	s.save()

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
	from retail_store.tests.capability_links import missing

	gaps = missing("enable_crm", "owner@demo.example")
	check("Store Owner can read every CRM lookup master (no 403 on save)", set(gaps) <= {"DocType"}, gaps)
	blocked_for = lambda user: frappe.get_all("Block Module", filters={"parent": user}, pluck="module")
	check("CRM stays blocked for Store Admin (holds no CRM grants)", "CRM" in blocked_for("admin@demo.example"))
	check("CRM visible for Store Owner", "CRM" not in blocked_for("owner@demo.example"))
	check("CRM stays blocked for Cashier", "CRM" in blocked_for("cashier.downtown@demo.example"))
	check("Store Admin holds no CRM doctype grant", not frappe.db.exists("Custom DocPerm", {"parent": "Lead", "role": "Store Admin"}))
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

	# --- Online Store (only meaningful where the webshop app is installed)
	if "webshop" in frappe.get_installed_apps():
		from retail_store.setup.capabilities import OFFLINE_GATEWAY
		from retail_store.storefront import set_online_order_warehouse, website_warehouse
		from retail_store.tests.capability_links import missing as missing_links

		s.enable_ecommerce = 1
		s.save()
		ws = frappe.get_single("Webshop Settings")
		check("Online Store: Webshop switched on", ws.enabled)
		check("Online Store: shows prices, stock and the variant picker", ws.show_price and ws.show_stock_availability and ws.enable_variants)
		check("Online Store: a selling price list is chosen", bool(ws.price_list) and bool(frappe.db.get_value("Price List", ws.price_list, "selling")), ws.price_list)
		gateway = frappe.db.get_value("Payment Gateway Account", ws.payment_gateway_account, "payment_gateway") if ws.payment_gateway_account else None
		check("Online Store: checkout is on (Place Order), via the offline gateway when none is chosen", ws.enable_checkout and bool(gateway), (ws.enable_checkout, gateway, OFFLINE_GATEWAY))
		site = frappe.get_single("Website Settings")
		check("Online Store: the shop is the public home page", bool(site.home_page), site.home_page)
		check("Online Store: public navbar carries the brand logo", bool(s.brand_logo) and site.banner_image == s.brand_logo, site.banner_image)
		check("Online Store: footer carries the brand name", site.footer_powered == s.brand_name, site.footer_powered)
		check("Store Owner holds Website Item and Website Slideshow", all(frappe.db.exists("Custom DocPerm", {"parent": dt, "role": "Store Owner"}) for dt in ("Website Item", "Website Slideshow")))
		gaps = missing_links("enable_ecommerce", "owner@demo.example")
		check("Store Owner can read every Online Store lookup (no 403 on save)", set(gaps) <= {"DocType"}, gaps)
		check("Portal customers may read Customer (own record only, via hooks)", frappe.db.exists("Custom DocPerm", {"parent": "Customer", "role": "Customer", "read": 1}))
		main = frappe.db.get_single_value("Retail Store Settings", "main_warehouse")
		generic = frappe.db.get_single_value("Stock Settings", "default_warehouse")
		cart = frappe._dict(order_type="Shopping Cart", items=[frappe._dict(item_code="ZZ-NO-WEBSITE-ITEM", warehouse=generic)])
		set_online_order_warehouse(cart)
		check("A cart line left on the generic default warehouse moves to Main", cart["items"][0].warehouse == main, (cart["items"][0].warehouse, main, generic))
		other = frappe._dict(order_type="Sales Invoice", items=[frappe._dict(item_code="ZZ-NO-WEBSITE-ITEM", warehouse=generic)])
		set_online_order_warehouse(other)
		check("Non-cart documents are left alone", other["items"][0].warehouse == generic)
		if frappe.db.exists("Website Item", {"item_code": "DEMO-SNEAKER"}) and frappe.db.exists("Item", "DEMO-SNEAKER-42-WHIT"):
			template_wh = frappe.db.get_value("Website Item", {"item_code": "DEMO-SNEAKER"}, "website_warehouse")
			check("A VARIANT takes its template's website warehouse", website_warehouse("DEMO-SNEAKER-42-WHIT") == template_wh, (website_warehouse("DEMO-SNEAKER-42-WHIT"), template_wh))
			line = frappe._dict(order_type="Shopping Cart", items=[frappe._dict(item_code="DEMO-SNEAKER-42-WHIT", warehouse=None)])
			set_online_order_warehouse(line)
			check("...and a blank cart line for that variant gets it", line["items"][0].warehouse == template_wh, line["items"][0].warehouse)

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

	# --- Branding + optional-module toggles are System Manager only (permlevel 1)
	meta = frappe.get_meta("Retail Store Settings")
	level1 = {df.fieldname for df in meta.fields if df.permlevel == 1}
	check(
		"Branding and optional-module toggles sit at permlevel 1",
		{"brand_name", "brand_logo", "brand_color", "accent_color", "enable_crm", "enable_ecommerce", "enable_buying"} <= level1,
		sorted(level1),
	)
	check(
		"Operational settings stay at permlevel 0",
		not ({"main_warehouse", "require_request_approval", "default_loyalty_program", "enable_loyalty"} & level1),
	)
	grants = {
		(r.role, r.permlevel): (r.read, r.write)
		for r in frappe.get_all("Custom DocPerm", filters={"parent": "Retail Store Settings"}, fields=["role", "permlevel", "read", "write"])
	}
	check("Only System Manager holds permlevel 1", {k[0] for k in grants if k[1] == 1} == {"System Manager"}, grants)
	check("System Manager can read+write permlevel 1", grants.get(("System Manager", 1)) == (1, 1))
	for role in ("Store Owner", "Store Admin"):
		check(f"{role} keeps operational (permlevel 0) read+write", grants.get((role, 0)) == (1, 1))
	# Store Owner also edits the Messages connection (permlevel 2: WhatsApp / SMS credentials); Store Admin does not
	for owner_like, expected in (("owner@demo.example", {0, 2}), ("admin@demo.example", {0})):
		frappe.set_user(owner_like)
		access = frappe.get_doc("Retail Store Settings").get_permlevel_access("write")
		frappe.set_user("Administrator")
		check(f"{owner_like} can write permlevels {sorted(expected)} only (never the Branding / Capabilities level 1)", set(access) == expected, access)

	# --- Customer defaults: ERPNext leaves Customer Group / Territory blank
	ss = frappe.get_single("Selling Settings")
	check("Selling Settings has a default Customer Group", bool(ss.customer_group), ss.customer_group)
	check("Selling Settings has a default Territory", bool(ss.territory), ss.territory)
	check("Customer Group default is a leaf (assignable)", frappe.db.get_value("Customer Group", ss.customer_group, "is_group") == 0)
	check("Territory default is a leaf (assignable)", frappe.db.get_value("Territory", ss.territory, "is_group") == 0)
	check("Site default feeds ERPNext's Lead conversion", frappe.db.get_default("Customer Group") == ss.customer_group)
	probe = frappe.get_doc({"doctype": "Customer", "customer_name": "ZZ Defaults Probe", "customer_type": "Individual"})
	probe.insert(ignore_permissions=True)
	check(
		"A Customer created with neither gets both defaults",
		(probe.customer_group, probe.territory) == (ss.customer_group, ss.territory),
		(probe.customer_group, probe.territory),
	)
	frappe.delete_doc("Customer", probe.name, force=True, ignore_permissions=True)
	for contact in frappe.get_all("Contact", filters={"first_name": "ZZ Defaults Probe"}, pluck="name"):
		frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)

	# --- navigation for a cashier
	frappe.set_user("cashier.downtown@demo.example")
	user = frappe.get_doc("User", "cashier.downtown@demo.example")
	check("Per-user theme profile picker is off (one brand identity per site)", not frappe.db.get_single_value("Theme Settings", "allow_user_theme"))
	check("Today's View switched on in the theme (System Manager keeps it)", frappe.db.get_single_value("Theme Settings", "enable_smart_home") and "\"enable_smart_home\": true" in (frappe.db.get_single_value("Theme Settings", "theme_studio_config") or ""))
	check("No stored per-user theme profiles", not frappe.db.count("Theme Preference"))
	previous_user = frappe.session.user
	for who, want in (("cashier.downtown@demo.example", False), ("owner@demo.example", False), ("Administrator", True)):
		frappe.set_user(who)
		check(f"Workspace create right: {who} = {want}", bool(frappe.has_permission("Workspace", "create")) == want)
	frappe.set_user(previous_user)
	check("Retail staff land in Retail Store app", user.get("default_app") == "retail_store", user.get("default_app"))
	from retail_store.branding import has_app_permission

	check("Retail Store app tile permitted for cashier", has_app_permission())
	from frappe.utils.modules import is_module_visible

	check("Manufacturing hidden for cashier", not is_module_visible("Manufacturing"))
	# Accounts / Selling / Stock rail buttons are for back-office roles only: a cashier must not
	# be shown a button that answers "Not permitted" (workspace_access.py enforces the same roles).
	for module in ("Stock", "Selling", "Accounts"):
		check(f"{module} hidden for cashier", not is_module_visible(module))
	frappe.set_user("owner@demo.example")
	for module in ("Stock", "Selling", "Accounts"):
		check(f"{module} visible for owner", is_module_visible(module))
	frappe.set_user("Administrator")

	# --- restore
	s.reload()
	for f in ("brand_name", "brand_color", "brand_logo", "enable_crm", "enable_ecommerce", "enable_loyalty"):
		s.set(f, original.get(f))
	s.save()
	frappe.db.commit()

	failed = [r for r in results if not r[1]]
	print(f"\n{len(results) - len(failed)}/{len(results)} config checks passed")
