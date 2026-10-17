"""Online Store front page: banner, categories, newest products.

Webshop's own home is the product list ("All Products"), which has no banner or entry points for a
shopper arriving cold. This page is the site home (Website Settings > Home Page, set by
setup_webshop_defaults) and links into webshop's own pages. Text and image are per-client fields on
Retail Store Settings (Storefront Home Page); everything else is read from published Website Items.
"""

import frappe
from frappe import _
from retail_store.storefront import product_card as _card

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
	context.rs_hero_art = [p for p in context.rs_new if p.get('image')][:4]  # fills the right half of the banner
	context.rs_categories = _categories(items)
	context.rs_has_products = bool(items)


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
