"""Online Store (webshop) glue, found by walking a real customer through checkout.

1. Variants: customers buy a VARIANT (DEMO-SNEAKER-42-WHIT) but only the template has a Website
   Item, so the cart finds no website_warehouse for the line and ERPNext falls back to Stock
   Settings' default warehouse ("Stores"), which holds no stock. Shopping-cart lines now take
   the template's website warehouse, else the retail Main warehouse.

2. Portal customers and their own Customer record: webshop's order page calls ERPNext's
   loyalty-points lookup, which requires read permission on the Customer doctype. A portal user
   has none, so every customer enrolled in a loyalty program (all of ours) saw "Not Permitted"
   on their own order page after paying. Website Users are given read on Customer, and the hooks
   below confine that to the customers they are a Portal User of.
"""

import frappe


def website_warehouse(item_code):
	"""The warehouse a Website Item names: the item's own, else its template's (variants)."""
	template = frappe.db.get_value("Item", item_code, "variant_of")
	for code in (item_code, template):
		if code:
			warehouse = frappe.db.get_value("Website Item", {"item_code": code}, "website_warehouse")
			if warehouse:
				return warehouse
	return None


def set_online_order_warehouse(doc, method=None):
	"""Quotation / Sales Order before_validate: put shopping-cart lines on the warehouse that fulfils online orders.

	An explicit website warehouse (own or template's) always wins. Otherwise a line that is blank,
	or that ERPNext has already filled with Stock Settings' generic default ("Stores"), moves to
	the retail Main warehouse. ERPNext fills that default before validation, so "only if blank"
	is not enough."""
	if doc.get("order_type") != "Shopping Cart":
		return
	generic = frappe.db.get_single_value("Stock Settings", "default_warehouse")
	main = frappe.db.get_single_value("Retail Store Settings", "main_warehouse")
	for row in doc.get("items") or []:
		explicit = website_warehouse(row.item_code)
		if explicit:
			row.warehouse = explicit
		elif main and (not row.get("warehouse") or row.warehouse == generic):
			row.warehouse = main


def _is_website_user(user):
	return frappe.db.get_value("User", user, "user_type") == "Website User"


def _own_customers(user):
	return frappe.get_all("Portal User", filters={"user": user, "parenttype": "Customer"}, pluck="parent")


def customer_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if not _is_website_user(user):
		return ""
	own = _own_customers(user)
	if not own:
		return "1=0"
	return "`tabCustomer`.name in ({0})".format(", ".join(frappe.db.escape(c) for c in own))


def customer_has_permission(doc, ptype=None, user=None, debug=False):
	"""Website Users may only read (never write) a Customer they are a Portal User of."""
	user = user or frappe.session.user
	if not _is_website_user(user):
		return True
	return ptype in (None, "read", "select") and doc.get("name") in _own_customers(user)


def hide_pay_link_for_offline_gateway(context):
	"""update_website_context: the order page offers "Pay <total>" whenever checkout is on, which for
	our offline gateway ("Pay in Store or on Delivery") opens a bare 403. Switch the link off only
	while that gateway is the active one; a real gateway shows it as normal. Runs after the page's
	own get_context, so it can override what the order page decided."""
	if not context.get("enabled_checkout"):
		return
	account = frappe.get_cached_doc("Webshop Settings").payment_gateway_account
	if account and frappe.db.get_value("Payment Gateway Account", account, "payment_gateway") == "Pay in Store or on Delivery":
		context.enabled_checkout = 0


SHOPPER_LOGIN = "/account/login"


def store_is_on():
	return "webshop" in frappe.get_installed_apps() and bool(frappe.get_cached_doc("Webshop Settings").enabled)


def shopper_login_url(context):
	"""update_website_context: where the storefront's "Login" link points.

	Staff keep /login (Solvronix's page, untouched). Shoppers get their own page at /account/login.
	Frappe's navbar partials hard-code "/login", so retail_store ships copies of them (templates/
	includes/navbar/) that use rs_login_url instead; with the Online Store off this stays unset and
	the partials fall back to /login, so nothing ever links to the shopper page."""
	if store_is_on():
		context.rs_login_url = SHOPPER_LOGIN


def default_thumbnail(doc, method=None):
	"""Website Item validate: a thumbnail for the search suggestions and cards.

	Webshop only builds a thumbnail for images stored as File records; a photo given as a plain URL
	(/assets/... as the demo photos are, or an external link) leaves `thumbnail` empty, and the search
	dropdown then shows its grey placeholder icon for an item that has a real photo. Reuse the image."""
	if doc.get("website_image") and not doc.get("thumbnail"):
		doc.thumbnail = doc.website_image


NO_MATCH = "__no_match__"


def _items_with_attributes(attributes):
	"""Website Item codes whose variants (or the item itself) carry EVERY selected attribute value.

	Webshop's own attribute filter looks for *published Items* carrying the attribute. A variant shop
	publishes only the template (the variants are not on the website), and the template's own
	attribute rows are empty, so every attribute filter came back with zero products. Resolve it
	through the variants instead: a template matches when a single variant satisfies all selected
	attributes (White AND 42 means a White size-42 variant, not "some white one and some 42 one")."""
	per_attribute = []
	for attribute, values in attributes.items():
		values = values if isinstance(values, list) else [values]
		if not values:
			continue
		rows = frappe.get_all(
			"Item Variant Attribute",
			filters={"attribute": attribute, "attribute_value": ["in", values], "parenttype": "Item"},
			pluck="parent",
		)
		per_attribute.append(set(rows))
	if not per_attribute:
		return None
	matching = set.intersection(*per_attribute)
	if not matching:
		return set()
	items = frappe.get_all("Item", filters={"name": ["in", list(matching)], "disabled": 0}, fields=["name", "variant_of"])
	return {item.variant_of or item.name for item in items}


@frappe.whitelist(allow_guest=True)
def get_product_filter_data(query_args=None):
	"""override of webshop.webshop.api.get_product_filter_data: same answer, but attribute filters
	are resolved through the variants (see _items_with_attributes) and handed on as an item_code filter."""
	if isinstance(query_args, str):
		query_args = frappe.parse_json(query_args)
	query_args = frappe._dict(query_args or {})
	attributes = frappe.parse_json(query_args.get("attribute_filters")) or {}
	if attributes:
		codes = _items_with_attributes(attributes)
		field_filters = frappe.parse_json(query_args.get("field_filters")) or {}
		if codes is not None:
			field_filters["item_code"] = sorted(codes) or [NO_MATCH]
		query_args["field_filters"] = field_filters
		query_args["attribute_filters"] = {}

	from webshop.webshop.api import get_product_filter_data as webshop_get_product_filter_data

	return webshop_get_product_filter_data(query_args)
