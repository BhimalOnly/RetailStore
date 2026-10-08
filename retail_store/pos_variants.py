"""POS: one card per product template, with a Size/Colour picker for variants.

Stock ERPNext v16 POS lists every variant as its own card (`get_items` filters
`has_variants == 0`) and has no variant picker. With "Group variants in POS"
on (Retail Store Settings, default on), this module:

* replaces the POS item list with one card per template plus every
  non-variant item, keeping ERPNext's paging, item-group, POS-profile,
  "hide unavailable" and search filters;
* serves the picker (`get_variant_options`), which the browser side
  (public/js/pos_variant_picker.js) shows when a template card is clicked;
* hands barcode / serial / batch scans and exact item codes straight to
  ERPNext's own `get_items`, so scanning a box adds the exact variant.

Everything is isolated here behind the toggle. If an ERPNext update changes the
POS, turn the toggle off and the stock behaviour comes back untouched.
"""

import frappe
from frappe.query_builder import Criterion, Order
from frappe.query_builder.functions import Coalesce, Count, Max, Sum
from frappe.utils import cint, flt, today
from frappe.utils.nestedset import get_root_of

from erpnext.accounts.doctype.pos_invoice.pos_invoice import get_stock_availability
from erpnext.selling.page.point_of_sale import point_of_sale as erpnext_pos
from erpnext.stock.get_item_details import get_conversion_factor


def grouping_enabled():
	# install/migrate writes the default (on); see install.ensure_single_defaults
	return bool(cint(frappe.db.get_single_value("Retail Store Settings", "group_variants_in_pos")))


def _is_direct_lookup(search_term):
	"""Scans and exact codes go to ERPNext untouched (exact variant, no picker)."""
	if not search_term:
		return False
	if frappe.db.exists("Item", {"name": search_term, "has_variants": 0}):
		return True
	return bool(erpnext_pos.search_for_serial_or_batch_or_barcode_number(search_term))


@frappe.whitelist()
def get_items(start, page_length, price_list, item_group, pos_profile, search_term=""):
	if not grouping_enabled() or _is_direct_lookup(search_term):
		return erpnext_pos.get_items(start, page_length, price_list, item_group, pos_profile, search_term)

	erpnext_pos.check_pos_profile_access(pos_profile)
	warehouse, hide_unavailable = frappe.db.get_value(
		"POS Profile", pos_profile, ["warehouse", "hide_unavailable_items"]
	)

	units = _display_units(start, page_length, item_group, pos_profile, search_term, warehouse, hide_unavailable)
	templates = [u.unit for u in units if u.is_variant]
	template_stats = _template_stats(templates, warehouse, price_list)
	plain = {row["item_code"]: row for row in _plain_cards([u.unit for u in units if not u.is_variant], warehouse, price_list)}

	result = []
	for u in units:
		card = template_stats.get(u.unit) if u.is_variant else plain.get(u.unit)
		if card:
			result.append(card)
	return {"items": result}


def _display_units(start, page_length, item_group, pos_profile, search_term, warehouse, hide_unavailable):
	"""One row per card: a template (any of its variants matched) or a plain item.

	Mirrors the filters of erpnext's get_items, evaluated on the sellable item
	(the variant), then collapsed onto its template.
	"""
	if not frappe.db.exists("Item Group", item_group):
		item_group = get_root_of("Item Group")
	lft, rgt = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"])

	item = frappe.qb.DocType("Item")
	template = frappe.qb.DocType("Item").as_("template")
	item_group_dt = frappe.qb.DocType("Item Group")
	group_subquery = (
		frappe.qb.from_(item_group_dt)
		.select(item_group_dt.name)
		.where((item_group_dt.lft >= lft) & (item_group_dt.rgt <= rgt))
	)

	unit = Coalesce(item.variant_of, item.name)
	query = (
		frappe.qb.from_(item)
		.left_join(template)
		.on(template.name == item.variant_of)
		.select(unit.as_("unit"), Max(item.variant_of.isnotnull()).as_("is_variant"))
		.where(
			(item.disabled == 0)
			& (item.has_variants == 0)
			& (item.is_sales_item == 1)
			& (item.is_fixed_asset == 0)
			& (item.item_group.isin(group_subquery))
			& (item.variant_of.isnull() | (template.disabled == 0))
		)
		.groupby(unit)
		.orderby(unit, order=Order.asc)
		.limit(cint(page_length))
		.offset(cint(start))
	)
	if search_term:
		# match the variant (code, name, POS search fields) or its template's name
		pattern = f"%{search_term}%"
		query = query.where(
			Criterion.any(
				[
					erpnext_pos.get_conditions(search_term, item),
					template.name.like(pattern),
					template.item_name.like(pattern),
				]
			)
		)
	group_condition = erpnext_pos.get_item_group_condition(pos_profile, item)
	if group_condition is not None:
		query = query.where(group_condition)
	if hide_unavailable:
		bin_dt = frappe.qb.DocType("Bin")
		query = (
			query.left_join(bin_dt)
			.on((bin_dt.item_code == item.name) & (bin_dt.warehouse == warehouse))
			.where((item.is_stock_item == 0) | (bin_dt.actual_qty > 0))
		)
	return query.run(as_dict=True)


def _price_rows(item_codes, price_list):
	"""Valid selling prices for the items, newest valid_from first (ERPNext's ordering)."""
	if not item_codes:
		return []
	ip = frappe.qb.DocType("Item Price")
	now = today()
	return (
		frappe.qb.from_(ip)
		.select(ip.item_code, ip.price_list_rate, ip.currency, ip.uom, ip.batch_no)
		.where(
			(ip.price_list == price_list)
			& (ip.item_code.isin(item_codes))
			& (ip.selling == 1)
			& ((ip.valid_from <= now) | ip.valid_from.isnull())
			& ((ip.valid_upto >= now) | ip.valid_upto.isnull())
		)
		.orderby(ip.valid_from, order=Order.desc)
		.run(as_dict=True)
	)


def _stock_uom_price(prices, item_code, stock_uom):
	rows = [p for p in prices if p.item_code == item_code]
	return next((p for p in rows if p.uom in (stock_uom, None, "")), rows[0] if rows else None)


def _variant_prices(template_names, price_list):
	"""item_code -> price row for every variant; a variant without its own price
	falls back to the template's price, as ERPNext's pricing does."""
	if not template_names:
		return {}, {}
	variants = frappe.get_all(
		"Item",
		filters={"variant_of": ["in", template_names], "disabled": 0, "is_sales_item": 1},
		fields=["name", "variant_of", "stock_uom"],
	)
	prices = _price_rows([v.name for v in variants] + list(template_names), price_list)
	result = {}
	for v in variants:
		result[v.name] = _stock_uom_price(prices, v.name, v.stock_uom) or _stock_uom_price(
			prices, v.variant_of, v.stock_uom
		)
	return result, variants


def _template_stats(template_names, warehouse, price_list):
	if not template_names:
		return {}
	variant_prices, variants = _variant_prices(template_names, price_list)

	item = frappe.qb.DocType("Item")
	bin_dt = frappe.qb.DocType("Bin")
	stock = dict(
		frappe.qb.from_(item)
		.left_join(bin_dt)
		.on((bin_dt.item_code == item.name) & (bin_dt.warehouse == warehouse))
		.select(item.variant_of, Sum(Coalesce(bin_dt.actual_qty, 0)))
		.where(item.variant_of.isin(template_names) & (item.disabled == 0) & (item.is_sales_item == 1))
		.groupby(item.variant_of)
		.run()
	)
	counts = dict(
		frappe.qb.from_(item)
		.select(item.variant_of, Count(item.name))
		.where(item.variant_of.isin(template_names) & (item.disabled == 0) & (item.is_sales_item == 1))
		.groupby(item.variant_of)
		.run()
	)

	cards = {}
	for t in frappe.get_all(
		"Item",
		filters={"name": ["in", template_names]},
		fields=["name", "item_name", "description", "stock_uom", "image", "is_stock_item", "item_group"],
	):
		rates = [p for v in variants if v.variant_of == t.name and (p := variant_prices.get(v.name))]
		low = min(rates, key=lambda p: p.price_list_rate) if rates else None
		high = max((p.price_list_rate for p in rates), default=None)
		cards[t.name] = {
			"item_code": t.name,
			"item_name": t.item_name,
			"description": t.description,
			"item_group": t.item_group,
			"stock_uom": t.stock_uom,
			"uom": t.stock_uom,
			"item_image": t.image or _first_variant_image(t.name),
			"is_stock_item": t.is_stock_item,
			"actual_qty": flt(stock.get(t.name)),
			"price_list_rate": low.price_list_rate if low else None,
			"currency": low.currency if low else None,
			"batch_no": None,
			"rs_is_template": 1,
			"rs_variant_count": counts.get(t.name, 0),
			"rs_price_max": high,
		}
	return cards


def _first_variant_image(template):
	return frappe.db.get_value("Item", {"variant_of": template, "image": ["is", "set"]}, "image")


def _plain_cards(item_codes, warehouse, price_list):
	"""Same card ERPNext builds for a non-variant item (UOM/price logic mirrored
	from erpnext.selling.page.point_of_sale.point_of_sale.get_items)."""
	if not item_codes:
		return []
	rows = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=[
			"name as item_code",
			"item_name",
			"description",
			"stock_uom",
			"image as item_image",
			"is_stock_item",
			"sales_uom",
			"item_group",
		],
	)
	prices = _price_rows(item_codes, price_list)
	cards = []
	for item in rows:
		item.actual_qty, _, _ = get_stock_availability(item.item_code, warehouse)
		item_prices = [p for p in prices if p.item_code == item.item_code]
		item_uom = item.stock_uom
		price = next((p for p in item_prices if p.uom == item.stock_uom), None)
		if item.sales_uom and item.sales_uom != item.stock_uom:
			sales_price = next((p for p in item_prices if p.uom == item.sales_uom), None)
			if sales_price:
				item_uom, price = item.sales_uom, sales_price
		if item_prices and not price:
			price = item_prices[0]
			item_uom = price.uom or item.stock_uom
		factor = get_conversion_factor(item.item_code, item_uom).get("conversion_factor") or 1
		if item.stock_uom != item_uom:
			item.actual_qty = item.actual_qty // factor
		rate = price.price_list_rate if price else None
		if price and price.uom and item_uom != price.uom:
			rate = rate * factor
		cards.append(
			{
				**item,
				"price_list_rate": rate,
				"currency": price.currency if price else None,
				"uom": item_uom,
				"batch_no": price.batch_no if price else None,
			}
		)
	return cards


@frappe.whitelist()
def get_variant_options(template, pos_profile, price_list=None):
	"""Data for the picker: the template's attributes (in order) and every
	sellable variant with its attribute values, stock at this till and price."""
	erpnext_pos.check_pos_profile_access(pos_profile)
	warehouse, profile_price_list = frappe.db.get_value(
		"POS Profile", pos_profile, ["warehouse", "selling_price_list"]
	)
	price_list = price_list or profile_price_list

	attributes = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": template, "parenttype": "Item"},
		pluck="attribute",
		order_by="idx",
	)
	prices, variants = _variant_prices([template], price_list)
	values = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": ["in", [v.name for v in variants] or [""]], "parenttype": "Item"},
		fields=["parent", "attribute", "attribute_value"],
	)

	# keep each attribute's values in the order defined on the Item Attribute (36, 37 ... not 36, 40, 37)
	order = {}
	for attribute in attributes:
		for i, v in enumerate(
			frappe.get_all(
				"Item Attribute Value", filters={"parent": attribute}, pluck="attribute_value", order_by="idx"
			)
		):
			order[(attribute, v)] = i

	rows = []
	for v in variants:
		qty, is_stock_item, _ = get_stock_availability(v.name, warehouse)
		price = prices.get(v.name)
		rows.append(
			{
				"item_code": v.name,
				"stock_uom": v.stock_uom,
				"actual_qty": qty,
				"is_stock_item": is_stock_item,
				"rate": price.price_list_rate if price else None,
				"currency": price.currency if price else None,
				"attributes": {r.attribute: r.attribute_value for r in values if r.parent == v.name},
			}
		)

	options = {}
	for attribute in attributes:
		seen = {r["attributes"].get(attribute) for r in rows} - {None}
		options[attribute] = sorted(seen, key=lambda val: (order.get((attribute, val), 999), val))

	return {
		"template": template,
		"item_name": frappe.db.get_value("Item", template, "item_name"),
		"attributes": attributes,
		"options": options,
		"variants": rows,
		"allow_negative_stock": cint(frappe.db.get_single_value("Stock Settings", "allow_negative_stock")),
	}
