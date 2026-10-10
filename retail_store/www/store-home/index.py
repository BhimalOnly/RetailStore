"""Online Store front page: banner, categories, newest products.

Webshop's own home is the product list ("All Products"), which has no banner or entry points for a
shopper arriving cold. This page is the site home (Website Settings > Home Page, set by
setup_webshop_defaults) and links into webshop's own pages. Text and image are per-client fields on
Retail Store Settings (Storefront Home Page); everything else is read from published Website Items.
"""

import frappe
from frappe import _
from frappe.utils import fmt_money

no_cache = 1
NEWEST = 8


def get_context(context):
	context.no_cache = 1
	context.full_width = True
	settings = frappe.get_cached_doc("Retail Store Settings")
	brand = settings.brand_name or frappe.get_website_settings("app_name") or "our store"
	context.title = brand
	context.rs_headline = settings.storefront_headline or _("Welcome to {0}").format(brand)
	context.rs_tagline = settings.storefront_tagline or ""
	context.rs_hero = settings.storefront_hero_image or ""

	items = frappe.get_all(
		"Website Item",
		filters={"published": 1},
		fields=["name", "item_code", "web_item_name", "website_image", "route", "item_group", "has_variants"],
		order_by="creation desc",
	)
	context.rs_new = [_card(i) for i in items[:NEWEST]]
	context.rs_categories = _categories(items)
	context.rs_has_products = bool(items)


def _card(item):
	return {
		"title": item.web_item_name,
		"route": "/" + (item.route or ""),
		"image": item.website_image,
		"abbr": frappe.utils.get_abbr(item.web_item_name or ""),
		"group": item.item_group,
		"price": _price(item),
	}


def _price(item):
	"""List price for a plain item; blank for a variant template (its price depends on the pick)."""
	if item.has_variants:
		return ""
	price_list = frappe.get_cached_doc("Webshop Settings").price_list
	if not price_list:
		return ""
	rate = frappe.db.get_value("Item Price", {"item_code": item.item_code, "price_list": price_list}, "price_list_rate")
	currency = frappe.db.get_value("Price List", price_list, "currency")
	return fmt_money(rate, currency=currency) if rate else ""


def _categories(items):
	"""One tile per item group that has published products AND a web page (route), using its newest
	product's photo. A group without a route would be a dead link, so it is left out."""
	seen = {}
	for item in items:
		if item.item_group in seen:
			continue
		route = frappe.db.get_value("Item Group", item.item_group, "route")
		if route:
			seen[item.item_group] = {"title": item.item_group, "route": "/" + route, "image": item.website_image}
	return list(seen.values())
