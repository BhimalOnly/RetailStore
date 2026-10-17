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
from frappe import _
from frappe.utils import fmt_money


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
		# storefront.js reads this to say "pay in store" on the order page (it cannot see the context)
		context.body_class = f"{context.get('body_class') or ''} rs-pay-offline".strip()


def readable_order_items(context):
	"""update_website_context: the order page prints each line's item CODE ("DEMO-SNEAKER-40-WHIT").
	Show the product name and its options ("DEMO Everyday Sneaker (40, White)") instead. Display only:
	the document in the context is never saved."""
	doc = context.get("doc")
	# never the cart (Quotation): its quantity / remove buttons key on item_code
	if not doc or doc.get("doctype") not in ("Sales Order", "Sales Invoice", "Delivery Note"):
		return
	names = {}
	for d in doc.get("items") or []:
		code = d.get("item_code")
		if code not in names:
			names[code] = _shopper_item_name(code, d.get("item_name"))
		d.item_code = names[code]


def _shopper_item_name(item_code, item_name):
	variant_of = frappe.db.get_value("Item", item_code, "variant_of")
	if not variant_of:
		return item_name or item_code
	base = frappe.db.get_value("Item", variant_of, "item_name") or item_name or item_code
	options = frappe.get_all("Item Variant Attribute", filters={"parent": item_code}, fields=["attribute_value"], order_by="idx")
	values = [o.attribute_value for o in options if o.attribute_value]
	return f"{base} ({', '.join(values)})" if values else base


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


@frappe.whitelist(allow_guest=True)
def get_card_variants(item_codes):
	"""Colour/size options for the variant templates on a product grid (swatches, quick view).

	One call for a whole page of cards. Each template's options come from webshop's own
	variant_selector.get_attributes_and_values, the function behind the product page's picker, so the
	values are exactly the ones that exist as real variants, in the order the Item Attribute defines.
	Only published templates are answered for (this is open to guests)."""
	from webshop.webshop.variant_selector.utils import get_attributes_and_values

	codes = frappe.parse_json(item_codes) or []
	published = set(
		frappe.get_all("Website Item", filters={"item_code": ["in", codes[:60]], "published": 1, "has_variants": 1}, pluck="item_code")
	)
	out = {}
	for code in codes[:60]:
		if code in published:
			out[code] = [{"attribute": a["attribute"], "values": a["values"]} for a in get_attributes_and_values(code) if a.get("values")]
	return out


@frappe.whitelist(allow_guest=True)
def get_next_attribute_and_values(item_code, selected_attributes):
	"""override of webshop's variant_selector.get_next_attribute_and_values: correct stock for a variant.

	It computes `available_qty` from the Website Item of the matched VARIANT's warehouse, but a variant
	shop publishes only the template, so a variant with 60 units in the website warehouse came back as 0
	("out of stock") from the picker. webshop's own get_web_item_qty_in_stock already falls back to the
	template's warehouse for a variant (the cards and the cart use it), so reuse that for the match."""
	from webshop.webshop.variant_selector.utils import get_next_attribute_and_values as webshop_next
	from webshop.webshop.utils.product import get_web_item_qty_in_stock

	result = webshop_next(item_code, selected_attributes)
	matched = result.get("exact_match") or []
	if len(matched) == 1:
		result["available_qty"] = get_web_item_qty_in_stock(matched[0], "website_warehouse").stock_qty
	return result


@frappe.whitelist()
def get_cart_quotation(doc=None):
	"""override of webshop's get_cart_quotation, same answer plus the amounts formatted the way the
	cart page prints them ("Rs 2,700.00"), so the cart drawer matches the rest of the store."""
	from webshop.webshop.shopping_cart.cart import get_cart_quotation as webshop_cart

	result = webshop_cart(doc)
	quotation = result["doc"]
	result["formatted"] = {
		"total": quotation.get_formatted("total"),
		"lines": {row.item_code: {"amount": row.get_formatted("amount"), "rate": row.get_formatted("rate")} for row in quotation.get("items", [])},
	}
	return result


@frappe.whitelist()
def update_cart(item_code, qty, additional_notes=None, with_items=False):
	"""override of webshop's update_cart: removing the LAST line no longer crashes.

	Webshop deletes an emptied cart Quotation and then returns {"name": quotation.name} for a
	quotation it has just set to None: AttributeError, HTTP 500, and the request rolls back, so the line
	stays in the cart. (Its cart page avoids this only because it always asks for the rendered cart, with
	with_items.) The delete has already succeeded by then, so answer for that one case and re-raise
	anything else."""
	from webshop.webshop.shopping_cart.cart import update_cart as webshop_update_cart

	try:
		return webshop_update_cart(item_code, qty, additional_notes, with_items)
	except AttributeError:
		if frappe.utils.flt(qty) == 0 and not frappe.utils.cint(with_items):
			return {"name": None}
		raise


# ---- product page: description heading + "You may also like" ---------------------------------------------

RELATED = 4


def product_card(item):
	"""One .rs-prod tile (store-home's New arrivals and the product page's cross-sell row)."""
	return {
		"title": item.web_item_name,
		"route": "/" + (item.route or ""),
		"image": item.website_image,
		"abbr": frappe.utils.get_abbr(item.web_item_name or ""),
		"group": item.item_group,
		"price": list_price(item),
	}


def list_price(item):
	"""List price for a plain item; blank for a variant template (its price depends on the pick)."""
	if item.has_variants:
		return ""
	price_list = frappe.get_cached_doc("Webshop Settings").price_list
	if not price_list:
		return ""
	rate = frappe.db.get_value("Item Price", {"item_code": item.item_code, "price_list": price_list}, "price_list_rate")
	currency = frappe.db.get_value("Price List", price_list, "currency")
	return fmt_money(rate, currency=currency) if rate else ""


def _related_items(doc):
	"""Other published products from the same Item Group, topped up with the newest others so the row
	is never a lone tile. Webshop's own "Recommended" is a hand-picked per-item table, so there is
	nothing to reuse for this."""
	fields = ["name", "item_code", "web_item_name", "website_image", "route", "item_group", "has_variants"]
	base = {"published": 1, "name": ["!=", doc.name]}
	same = frappe.get_all("Website Item", filters={**base, "item_group": doc.item_group}, fields=fields, order_by="creation desc", limit=RELATED)
	if len(same) < RELATED:
		taken = [doc.name] + [i.name for i in same]
		same += frappe.get_all("Website Item", filters={"published": 1, "name": ["not in", taken]}, fields=fields, order_by="creation desc", limit=RELATED - len(same))
	return [product_card(i) for i in same]


def product_page_extras(context):
	"""update_website_context: webshop's product page prints the description as bare text and stops
	after the add-to-cart block. Add a "Details" heading above the description and a cross-sell row
	below. Display only: the Website Item in the context is never saved. The row goes into
	`website_content`, the full-width slot the template prints under the product."""
	doc = context.get("doc")
	if not doc or doc.get("doctype") != "Website Item":
		return
	body = doc.web_long_description if frappe.utils.strip_html(doc.web_long_description or "") else doc.description
	if frappe.utils.strip_html(body or ""):
		doc.web_long_description = '<h2 class="rs-pdp-h">{0}</h2>{1}'.format(_("Details"), body)
	items = _related_items(doc)
	if items:
		html = frappe.render_template("retail_store/templates/includes/rs_related.html", {"items": items})
		doc.website_content = (doc.get("website_content") or "") + html
