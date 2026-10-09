"""DEMO DATA — proves the pattern end to end. Delete or replace per real client.

Everything created here is prefixed "DEMO" (or uses the @demo.example email
domain) so it is easy to spot and remove:

    bench --site <site> execute retail_store.demo.create_demo_data
    bench --site <site> execute retail_store.demo.delete_demo_data

Recommended: keep demo data on a separate demo site. Never run this on a live
client site.
"""

import zlib

import frappe
from frappe.utils import nowdate

from retail_store.setup.company import get_default_company

DEMO_PASSWORD = "RetailDemo#2026"
EMAIL_DOMAIN = "demo.example"

ITEM_GROUPS = ["DEMO Footwear", "DEMO Apparel"]

ATTRIBUTES = {
	"DEMO Shoe Size": [str(s) for s in range(36, 47)],
	"DEMO Apparel Size": ["XS", "S", "M", "L", "XL"],
	"DEMO Colour": ["Black", "White", "Brown", "Navy"],
}

# Each template picks only the attribute values relevant to it; ERPNext
# generates the sellable variant combinations.
TEMPLATES = [
	{
		"item_code": "DEMO-SNEAKER",
		"item_name": "DEMO Everyday Sneaker",
		"item_group": "DEMO Footwear",
		"rate": 2500,
		"valuation_rate": 1200,
		"values": {"DEMO Shoe Size": ["40", "41", "42"], "DEMO Colour": ["Black", "White"]},
		# bigger sizes cost more, so the POS card shows a price range
		"premium": {"DEMO Shoe Size": {"42": 200}},
	},
	{
		"item_code": "DEMO-TEE",
		"item_name": "DEMO Cotton Tee",
		"item_group": "DEMO Apparel",
		"rate": 800,
		"valuation_rate": 300,
		"values": {"DEMO Apparel Size": ["S", "M", "L"], "DEMO Colour": ["Black", "Navy"]},
	},
]

# A plain (non-variant) item, so the POS shows a mixed catalogue.
PLAIN_ITEMS = [
	{"item_code": "DEMO-TOTE", "item_name": "DEMO Canvas Tote Bag", "item_group": "DEMO Apparel", "rate": 350, "valuation_rate": 120},
]

MAIN = "DEMO Main Warehouse"
STORES = ["DEMO Store Downtown", "DEMO Store Mall", "DEMO Store Airport"]

# (email local part, full name, roles, locations). Roles combine freely.
USERS = [
	("owner", "DEMO Owner", ["Store Owner"], []),
	("admin", "DEMO Store Admin", ["Store Admin"], []),
	("accountant", "DEMO Accountant", ["Accounts Manager", "Accounts User"], []),
	("cashier.downtown", "DEMO Cashier Downtown", ["Store Cashier"], ["DEMO Store Downtown"]),
	("cashier.mall", "DEMO Attendant+Cashier Mall", ["Store Attendant", "Store Cashier"], ["DEMO Store Mall"]),
	("floater", "DEMO Rotating Cashier", ["Store Cashier", "Store Attendant"], ["DEMO Store Downtown", "DEMO Store Airport"]),
	("manager.downtown", "DEMO Manager Downtown", ["Store Manager"], ["DEMO Store Downtown"]),
	("wh.manager", "DEMO Warehouse Manager", ["Warehouse Manager"], [MAIN]),
	("wh.attendant", "DEMO Warehouse Attendant", ["Warehouse Attendant"], [MAIN]),
]

CUSTOMERS = ["DEMO Walk-in Customer", "DEMO Jane Shopper"]


def email(local):
	return f"{local}@{EMAIL_DOMAIN}"


def create_demo_data():
	company = get_default_company()
	if not company:
		frappe.throw("Complete the Setup Wizard (create a Company) before creating demo data.")
	abbr = frappe.db.get_value("Company", company, "abbr")

	_item_groups()
	_attributes()
	variants = _templates()
	warehouses = _warehouses(company, abbr)
	_settings(warehouses)
	price_list = _prices(variants)
	_customers()
	_pos_profiles(company, warehouses, price_list)
	_opening_stock(company, warehouses, variants)
	_users(warehouses)
	publish_demo_website_items()
	create_demo_shopper()
	frappe.db.commit()
	print("DEMO data created. Users log in with password:", DEMO_PASSWORD)
	return {"warehouses": len(warehouses) - 1, "variants": len(variants)}


def _item_groups():
	parent = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}) or "All Item Groups"
	for name in ITEM_GROUPS:
		if not frappe.db.exists("Item Group", name):
			frappe.get_doc({"doctype": "Item Group", "item_group_name": name, "parent_item_group": parent}).insert()


def _attributes():
	for name, values in ATTRIBUTES.items():
		if frappe.db.exists("Item Attribute", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": name,
				"item_attribute_values": [{"attribute_value": v, "abbr": v.upper()[:4]} for v in values],
			}
		).insert()


def _templates():
	from erpnext.controllers.item_variant import create_variant, get_variant

	variants = {}
	for t in TEMPLATES:
		if not frappe.db.exists("Item", t["item_code"]):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": t["item_code"],
					"item_name": t["item_name"],
					"item_group": t["item_group"],
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"has_variants": 1,
					"valuation_rate": t["valuation_rate"],
					"description": "DEMO DATA - delete/replace per client",
					"attributes": [{"attribute": a} for a in t["values"]],
				}
			).insert()

		combos = [{}]
		for attribute, values in t["values"].items():
			combos = [{**c, attribute: v} for c in combos for v in values]
		for combo in combos:
			name = get_variant(t["item_code"], combo)
			if not name:
				v = create_variant(t["item_code"], combo)
				v.valuation_rate = t["valuation_rate"]
				v.insert()
				name = v.name
			premium = sum(t.get("premium", {}).get(a, {}).get(val, 0) for a, val in combo.items())
			variants[name] = {**t, "rate": t["rate"] + premium}
			_ensure_barcode(name)

	for p in PLAIN_ITEMS:
		if not frappe.db.exists("Item", p["item_code"]):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": p["item_code"],
					"item_name": p["item_name"],
					"item_group": p["item_group"],
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"valuation_rate": p["valuation_rate"],
					"description": "DEMO DATA - delete/replace per client",
				}
			).insert()
		_ensure_barcode(p["item_code"])
		variants[p["item_code"]] = p
	return variants


def _ensure_barcode(item_code):
	"""DEMO barcodes: 299 + 9 digits derived from the item code (no type, so no checksum rules)."""
	if frappe.db.exists("Item Barcode", {"parent": item_code}):
		return
	code = "299" + str(zlib.crc32(item_code.encode()) % 10**9).zfill(9)
	while frappe.db.exists("Item Barcode", {"barcode": code}):
		code = str(int(code) + 1)
	item = frappe.get_doc("Item", item_code)
	item.append("barcodes", {"barcode": code})
	item.save()


def _warehouses(company, abbr):
	parent = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ""})
	names = {}
	for wh in [MAIN, *STORES]:
		full = f"{wh} - {abbr}"
		if not frappe.db.exists("Warehouse", full):
			frappe.get_doc(
				{"doctype": "Warehouse", "warehouse_name": wh, "company": company, "parent_warehouse": parent}
			).insert()
		names[wh] = full
	transit = frappe.db.get_value("Company", company, "default_in_transit_warehouse") or frappe.db.get_value(
		"Warehouse", {"company": company, "warehouse_type": "Transit", "is_group": 0}
	)
	for wh in names.values():
		if transit and not frappe.db.get_value("Warehouse", wh, "default_in_transit_warehouse"):
			frappe.db.set_value("Warehouse", wh, "default_in_transit_warehouse", transit)
	names["transit"] = transit
	return names


def _settings(warehouses):
	s = frappe.get_single("Retail Store Settings")
	s.main_warehouse = warehouses[MAIN]
	if warehouses.get("transit"):
		s.in_transit_warehouse = warehouses["transit"]
	s.save()


def _prices(variants):
	price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, order_by="creation") or "Standard Selling"
	for item_code, t in variants.items():
		name = frappe.db.get_value("Item Price", {"item_code": item_code, "price_list": price_list})
		if not name:
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": item_code, "price_list": price_list, "price_list_rate": t["rate"]}
			).insert()
		elif frappe.db.get_value("Item Price", name, "price_list_rate") != t["rate"]:
			frappe.db.set_value("Item Price", name, "price_list_rate", t["rate"])
	return price_list


def _customers():
	group = frappe.db.get_value("Customer Group", {"is_group": 0}) or "Individual"
	territory = frappe.db.get_value("Territory", {"is_group": 0}) or "All Territories"
	for name in CUSTOMERS:
		if not frappe.db.exists("Customer", name):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": name,
					"customer_type": "Individual",
					"customer_group": group,
					"territory": territory,
				}
			).insert()


def _pos_profiles(company, warehouses, price_list):
	cash = "Cash"
	if not frappe.db.exists("Mode of Payment", cash):
		frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": cash, "type": "Cash"}).insert()
	cash_account = frappe.db.get_value("Account", {"company": company, "account_type": "Cash", "is_group": 0})
	mop = frappe.get_doc("Mode of Payment", cash)
	if cash_account and not any(a.company == company for a in mop.accounts):
		mop.append("accounts", {"company": company, "default_account": cash_account})
		mop.save()

	write_off = frappe.db.get_value("Company", company, "write_off_account") or frappe.db.get_value(
		"Account", {"company": company, "root_type": "Expense", "is_group": 0}
	)
	cost_center = frappe.db.get_value("Company", company, "cost_center")
	for store in STORES:
		name = f"DEMO POS {store.replace('DEMO Store ', '')}"
		if frappe.db.exists("POS Profile", name):
			continue
		frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": name,
				"__newname": name,
				"company": company,
				"warehouse": warehouses[store],
				"customer": CUSTOMERS[0],
				"selling_price_list": price_list,
				"currency": frappe.db.get_value("Company", company, "default_currency"),
				"update_stock": 1,
				"write_off_account": write_off,
				"write_off_cost_center": cost_center,
				"cost_center": cost_center,
				"payments": [{"mode_of_payment": cash, "default": 1}],
			}
		).insert()


def _opening_stock(company, warehouses, variants):
	stocked = set(frappe.get_all("Bin", filters={"warehouse": warehouses[MAIN]}, pluck="item_code"))
	variants = {code: t for code, t in variants.items() if code not in stocked}
	if not variants:
		return
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"company": company,
			"posting_date": nowdate(),
			"remarks": "DEMO opening stock",
		}
	)
	for item_code, t in variants.items():
		se.append("items", {"item_code": item_code, "t_warehouse": warehouses[MAIN], "qty": 50, "basic_rate": t["valuation_rate"]})
		for store in STORES:
			se.append("items", {"item_code": item_code, "t_warehouse": warehouses[store], "qty": 5, "basic_rate": t["valuation_rate"]})
	se.insert()
	se.submit()


def _users(warehouses):
	from frappe.utils.password import update_password

	for local, full_name, roles, locations in USERS:
		addr = email(local)
		if not frappe.db.exists("User", addr):
			first, _, last = full_name.partition(" ")
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": addr,
					"first_name": first,
					"last_name": last,
					"send_welcome_email": 0,
					"user_type": "System User",
					"roles": [{"role": r} for r in roles],
				}
			)
			user.flags.no_welcome_mail = True
			user.insert()
		update_password(addr, DEMO_PASSWORD)

		if frappe.db.exists("Retail Staff Access", addr):
			access = frappe.get_doc("Retail Staff Access", addr)
		else:
			access = frappe.get_doc({"doctype": "Retail Staff Access", "user": addr})
		access.set("locations", [{"warehouse": warehouses[w], "is_default": int(i == 0)} for i, w in enumerate(locations)])
		access.enabled = 1 if locations else 0
		access.save()


# ----------------------------------------------------------------------------
# Removal
# ----------------------------------------------------------------------------


def _cancel_and_delete(doctype, names):
	for name in names:
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.flags.ignore_links = True
			doc.cancel()
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)


LEDGERS = ("Stock Ledger Entry", "GL Entry", "Payment Ledger Entry", "Serial and Batch Bundle", "Repost Item Valuation")


def _purge_ledgers(voucher_type, voucher_no):
	"""Cancelled vouchers keep their ledger rows; remove them so DEMO warehouses can go."""
	for ledger in LEDGERS:
		if frappe.db.exists("DocType", ledger) and frappe.get_meta(ledger).has_field("voucher_no"):
			frappe.db.delete(ledger, {"voucher_type": voucher_type, "voucher_no": voucher_no})


def delete_demo_data():
	"""Remove DEMO masters and any transactions that touch DEMO warehouses/items."""
	demo_wh = frappe.get_all("Warehouse", filters={"warehouse_name": ["like", "DEMO %"]}, pluck="name")
	demo_items = frappe.get_all("Item", filters={"item_code": ["like", "DEMO-%"]}, pluck="name")
	frappe.flags.ignore_links = True

	# Online Store leftovers: storefront shopper, quotations and the Website Items for DEMO products
	for dt, filters in (("Address", {"address_title": "DEMO Jane Shopper"}), ("Contact", {"user": SHOPPER_EMAIL})):
		for name in frappe.get_all(dt, filters=filters, pluck="name"):
			frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
	if frappe.db.exists("User", SHOPPER_EMAIL):
		frappe.delete_doc("User", SHOPPER_EMAIL, force=True, ignore_permissions=True)
	if frappe.db.exists("DocType", "Website Item"):
		for name in frappe.get_all("Quotation Item", filters={"item_code": ["in", demo_items], "parenttype": "Quotation"}, pluck="parent", distinct=True) if demo_items else []:
			quotation = frappe.get_doc("Quotation", name)
			if quotation.docstatus == 1:
				quotation.flags.ignore_links = True
				quotation.cancel()
			frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Website Item", filters={"item_code": ["in", demo_items]}, pluck="name") if demo_items else []:
			frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)

	child_map = [
		("POS Invoice", "POS Invoice Item", "warehouse"),
		("Sales Invoice", "Sales Invoice Item", "warehouse"),
		("Stock Entry", "Stock Entry Detail", "s_warehouse"),
		("Stock Entry", "Stock Entry Detail", "t_warehouse"),
		("Material Request", "Material Request Item", "warehouse"),
		("Stock Reconciliation", "Stock Reconciliation Item", "warehouse"),
		("Delivery Note", "Delivery Note Item", "warehouse"),
		("Sales Order", "Sales Order Item", "warehouse"),
	]
	# Collect every touching transaction, then cancel newest-first ACROSS doctypes:
	# a transit receipt must be cancelled before the dispatch it came from.
	found = {}
	for parent, child, field in child_map if demo_wh else []:
		for name in frappe.get_all(child, filters={field: ["in", demo_wh], "parenttype": parent}, pluck="parent", distinct=True):
			found[(parent, name)] = frappe.db.get_value(parent, name, "creation")
	for (doctype, name), _created in sorted(found.items(), key=lambda kv: kv[1], reverse=True):
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.flags.ignore_links = True
			doc.cancel()
	for doctype, name in sorted(found, key=lambda k: found[k], reverse=True):
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		_purge_ledgers(doctype, name)

	for dt in ("POS Closing Entry", "POS Opening Entry"):
		names = frappe.get_all(dt, filters={"pos_profile": ["like", "DEMO POS %"]}, pluck="name", order_by="creation desc")
		_cancel_and_delete(dt, names)
	if demo_wh:
		frappe.db.delete("Stock Ledger Entry", {"warehouse": ["in", demo_wh]})

	for name in frappe.get_all("Loyalty Point Entry", filters={"customer": ["like", "DEMO %"]}, pluck="name"):
		frappe.delete_doc("Loyalty Point Entry", name, force=True, ignore_permissions=True)

	for local, *_ in USERS:
		addr = email(local)
		if frappe.db.exists("Retail Staff Access", addr):
			frappe.delete_doc("Retail Staff Access", addr, ignore_permissions=True)
		if frappe.db.exists("User", addr):
			frappe.delete_doc("User", addr, force=True, ignore_permissions=True)

	for name in frappe.get_all("POS Profile", filters={"name": ["like", "DEMO POS %"]}, pluck="name"):
		frappe.delete_doc("POS Profile", name, force=True, ignore_permissions=True)
	for name in frappe.get_all("Item Price", filters={"item_code": ["in", demo_items or [""]]}, pluck="name"):
		frappe.delete_doc("Item Price", name, force=True, ignore_permissions=True)
	for name in frappe.get_all("Bin", filters={"item_code": ["in", demo_items or [""]]}, pluck="name"):
		frappe.delete_doc("Bin", name, force=True, ignore_permissions=True)
	# variants (and plain items) before templates
	for name in frappe.get_all("Item", filters={"item_code": ["like", "DEMO-%"]}, pluck="name", order_by="has_variants asc"):
		frappe.delete_doc("Item", name, force=True, ignore_permissions=True)
	for name in CUSTOMERS:
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, force=True, ignore_permissions=True)
	for name in ATTRIBUTES:
		if frappe.db.exists("Item Attribute", name):
			frappe.delete_doc("Item Attribute", name, force=True, ignore_permissions=True)
	for name in ITEM_GROUPS:
		if frappe.db.exists("Item Group", name):
			frappe.delete_doc("Item Group", name, force=True, ignore_permissions=True)

	settings = frappe.get_single("Retail Store Settings")
	if settings.main_warehouse in demo_wh:
		frappe.db.set_single_value("Retail Store Settings", "main_warehouse", None)
	for name in demo_wh:
		frappe.delete_doc("Warehouse", name, force=True, ignore_permissions=True)

	frappe.flags.ignore_links = False
	frappe.db.commit()
	print("DEMO data removed.")


def refresh_pos_openings():
	"""Close any DEMO register opened on an earlier day and open a fresh one for today.

	ERPNext's POS refuses an opening entry from a previous day ("Outdated POS Opening
	Entry"), so demo/test tills go stale overnight. Run:
	    bench --site retail.localhost execute retail_store.demo.refresh_pos_openings
	"""
	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import make_closing_entry_from_opening

	today = frappe.utils.today()
	done = []
	for row in frappe.get_all(
		"POS Opening Entry",
		filters={"pos_profile": ["like", "DEMO POS %"], "status": "Open", "docstatus": 1},
		fields=["name", "user", "pos_profile", "company", "period_start_date"],
	):
		if str(row.period_start_date)[:10] >= today:
			continue
		closing = frappe.get_doc(make_closing_entry_from_opening(frappe.get_doc("POS Opening Entry", row.name).as_dict()))
		closing.period_end_date = frappe.utils.now_datetime()
		closing.posting_date = today
		for pr in closing.payment_reconciliation:
			pr.closing_amount = pr.expected_amount
		closing.insert(ignore_permissions=True)
		closing.submit()
		opening = frappe.get_doc(
			{
				"doctype": "POS Opening Entry",
				"pos_profile": row.pos_profile,
				"user": row.user,
				"company": row.company,
				"period_start_date": frappe.utils.now_datetime(),
				"posting_date": today,
				"balance_details": [{"mode_of_payment": "Cash", "opening_amount": 0}],
			}
		)
		opening.insert(ignore_permissions=True)
		opening.submit()
		done.append((row.pos_profile, row.name, closing.name, opening.name))
	frappe.db.commit()
	return done


def restock_pos_test_items(qty=10, main_qty=60):
	"""Top the demo test variants back up so the test suites can be re-run.

	tests/browser_pos.py sells one Downtown unit per run, and tests/e2e_section7.py moves
	units out of the Main warehouse every run, so both drain over repeated runs:
	    bench --site retail.localhost execute retail_store.demo.restock_pos_test_items
	"""
	company = "Demo Retail Co"
	abbr = frappe.db.get_value("Company", company, "abbr")
	targets = [
		(f"DEMO Store Downtown - {abbr}", "DEMO-SNEAKER-42-WHIT", qty),
		(f"DEMO Store Downtown - {abbr}", "DEMO-TEE-M-NAVY", qty),
		(f"DEMO Main Warehouse - {abbr}", "DEMO-SNEAKER-41-BLAC", main_qty),
		(f"DEMO Main Warehouse - {abbr}", "DEMO-TEE-M-NAVY", main_qty),
		# Online Store test orders (tests/browser_store.py) are fulfilled from Main
		(f"DEMO Main Warehouse - {abbr}", "DEMO-SNEAKER-42-WHIT", main_qty),
		(f"DEMO Main Warehouse - {abbr}", "DEMO-TOTE", main_qty),
	]
	made = []
	for warehouse in sorted({w for w, _, _ in targets}):
		rows = []
		for wh, item, want in targets:
			if wh != warehouse:
				continue
			have = frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "actual_qty") or 0
			if have < want:
				rows.append({"item_code": item, "qty": want - have, "t_warehouse": wh, "basic_rate": 1000})
		if not rows:
			continue
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": company,
				"remarks": "DEMO restock for test suites",
				"items": rows,
			}
		)
		se.insert(ignore_permissions=True)
		se.submit()
		made.append(se.name)
	frappe.db.commit()
	return made or "already stocked"


WEBSITE_DEMO_ITEMS = {
	"DEMO-SNEAKER": "Everyday sneaker with cushioned sole. Choose your size and colour.",
	"DEMO-TEE": "Soft cotton tee. Choose your size and colour.",
	"DEMO-TOTE": "Canvas tote bag.",
}


def publish_demo_website_items():
	"""Publish the demo products on the Online Store (needs the webshop app).

	No-op when webshop is not installed. Stock shown on the storefront comes from the Main
	warehouse, which fulfils online orders. Safe to run again.
	    bench --site retail.localhost execute retail_store.demo.publish_demo_website_items
	"""
	if not frappe.db.exists("DocType", "Website Item"):
		return []
	from webshop.webshop.doctype.website_item.website_item import make_website_item

	company = get_default_company()
	abbr = frappe.db.get_value("Company", company, "abbr")
	main = f"DEMO Main Warehouse - {abbr}"
	made = []
	for item_code, blurb in WEBSITE_DEMO_ITEMS.items():
		if not frappe.db.exists("Item", item_code):
			continue
		name = frappe.db.get_value("Website Item", {"item_code": item_code})
		if not name:
			name = make_website_item(frappe.get_doc("Item", item_code), save=True)[0]
		doc = frappe.get_doc("Website Item", name)
		doc.published = 1
		doc.website_warehouse = main if frappe.db.exists("Warehouse", main) else doc.website_warehouse
		doc.short_description = doc.short_description or blurb
		doc.flags.ignore_permissions = True
		doc.save()
		made.append(name)
	frappe.db.commit()
	return made


SHOPPER_EMAIL = "shopper@demo.example"


def create_demo_shopper():
	"""A storefront customer who can log in and order: portal user + contact + delivery address,
	all linked to the demo customer 'DEMO Jane Shopper' (Online Store testing).

	    bench --site retail.localhost execute retail_store.demo.create_demo_shopper
	"""
	customer = "DEMO Jane Shopper"
	if not frappe.db.exists("Customer", customer):
		return None
	if not frappe.db.exists("User", SHOPPER_EMAIL):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": SHOPPER_EMAIL,
				"first_name": "DEMO Jane",
				"last_name": "Shopper",
				"user_type": "Website User",
				"send_welcome_email": 0,
				"new_password": DEMO_PASSWORD,
				"roles": [{"role": "Customer"}],
			}
		).insert(ignore_permissions=True)
	contact = frappe.db.get_value("Contact", {"email_id": SHOPPER_EMAIL})
	if not contact:
		doc = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "DEMO Jane",
				"last_name": "Shopper",
				"user": SHOPPER_EMAIL,
				"email_ids": [{"email_id": SHOPPER_EMAIL, "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		)
		doc.insert(ignore_permissions=True)
	if not frappe.db.exists("Address", {"address_title": "DEMO Jane Shopper"}):
		country = frappe.db.get_value("Company", get_default_company(), "country") or "Mauritius"
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "DEMO Jane Shopper",
				"address_type": "Shipping",
				"address_line1": "12 Royal Road",
				"city": "Port Louis",
				"country": country,
				"is_primary_address": 1,
				"is_shipping_address": 1,
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		).insert(ignore_permissions=True)
	customer_doc = frappe.get_doc("Customer", customer)
	if not any(r.user == SHOPPER_EMAIL for r in customer_doc.get("portal_users") or []):
		customer_doc.append("portal_users", {"user": SHOPPER_EMAIL})
		customer_doc.flags.ignore_permissions = True
		customer_doc.save()
	frappe.db.commit()
	return SHOPPER_EMAIL


def purge_cancelled_test_orders():
	"""Delete CANCELLED storefront test documents (delivery notes, orders, quotations) for DEMO items.

	tests/browser_store.py cleans up by cancelling, which is what ERPNext allows: a cancelled
	document stays linked to its reversal ledger entries and cannot be deleted normally. On a demo
	site that clutter can be removed with the same ledger purge delete_demo_data uses:
	    bench --site retail.localhost execute retail_store.demo.purge_cancelled_test_orders
	"""
	frappe.flags.ignore_links = True
	removed = []
	for doctype, child in (
		("Delivery Note", "Delivery Note Item"),
		("Sales Order", "Sales Order Item"),
		("Quotation", "Quotation Item"),
	):
		names = frappe.get_all(child, filters={"item_code": ["like", "DEMO-%"], "parenttype": doctype}, pluck="parent", distinct=True)
		for name in names:
			if frappe.db.get_value(doctype, name, "docstatus") == 2:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
				_purge_ledgers(doctype, name)
				removed.append((doctype, name))
	frappe.db.commit()
	return removed
