// POS variant picker (Retail Store).
// Server side groups variants under their template (retail_store.pos_variants.get_items).
// Here: a template card shows "N options", and clicking it opens a Size/Colour
// picker; the chosen variant then goes through ERPNext's normal cart path.
// Methods are patched on the prototypes, which ERPNext looks up at call time,
// so this works whenever the POS bundle finishes loading.

frappe.provide("retail_store.pos");

retail_store.pos.template_cache = new Map(); // item_code -> is template (bool)

retail_store.pos.is_template = async function (item_code) {
	const cache = retail_store.pos.template_cache;
	if (!cache.has(item_code)) {
		const r = await frappe.db.get_value("Item", item_code, "has_variants");
		cache.set(item_code, !!(r.message && r.message.has_variants));
	}
	return cache.get(item_code);
};

retail_store.pos.pick_variant = function (controller, template) {
	return new Promise((resolve) => {
		frappe
			.call({
				method: "retail_store.pos_variants.get_variant_options",
				args: {
					template,
					pos_profile: controller.pos_profile || controller.settings?.name,
					price_list: controller.frm?.doc?.selling_price_list,
				},
			})
			.then(({ message: data }) => {
				if (!data || !data.variants.length) {
					frappe.show_alert({ message: __("No sellable variants for {0}", [template]), indicator: "orange" });
					return resolve(null);
				}
				retail_store.pos.show_picker(data, resolve);
			});
	});
};

retail_store.pos.show_picker = function (data, resolve) {
	const selected = {};
	let chosen = null;
	let done = false;
	const esc = frappe.utils.escape_html;

	const matches = (variant, sel) =>
		Object.entries(sel).every(([attr, val]) => variant.attributes[attr] === val);

	const dialog = new frappe.ui.Dialog({
		title: esc(data.item_name),
		fields: [{ fieldtype: "HTML", fieldname: "picker" }],
		primary_action_label: __("Add to Cart"),
		primary_action() {
			if (!chosen) return;
			done = true;
			dialog.hide();
			resolve(chosen);
		},
		on_hide() {
			if (!done) resolve(null);
		},
	});

	function render() {
		const $wrap = dialog.fields_dict.picker.$wrapper;
		let html = "";
		data.attributes.forEach((attr) => {
			html += `<div class="rs-attr"><div class="rs-attr-name">${esc(__(attr))}</div><div class="rs-chips">`;
			data.options[attr].forEach((val) => {
				// a value is offered only if some variant has it together with the other picks
				const others = Object.fromEntries(Object.entries(selected).filter(([a]) => a !== attr));
				const candidates = data.variants.filter((v) => v.attributes[attr] === val && matches(v, others));
				const exists = candidates.length > 0;
				const in_stock = candidates.some((v) => !v.is_stock_item || v.actual_qty > 0);
				const active = selected[attr] === val;
				const cls = `${active ? "is-active" : ""} ${in_stock || active ? "" : "is-out"}`;
				html += `<button type="button" class="rs-chip rs-opt ${cls}" data-attr="${esc(attr)}" data-val="${esc(val)}" ${
					exists ? "" : "disabled"
				}>${esc(val)}</button>`;
			});
			html += `</div></div>`;
		});

		const complete = data.attributes.every((a) => selected[a]);
		chosen = complete ? data.variants.find((v) => matches(v, selected)) || null : null;
		if (chosen) {
			const qty = chosen.is_stock_item ? chosen.actual_qty : __("Non stock item");
			const indicator = !chosen.is_stock_item || chosen.actual_qty > 10 ? "green" : chosen.actual_qty > 0 ? "orange" : "red";
			html += `<div class="rs-pick-summary">
				<div class="rs-pick-price">${chosen.rate != null ? format_currency(chosen.rate, chosen.currency) : __("No price")}</div>
				<span class="indicator-pill ${indicator}">${__("In stock here")}: ${qty}</span>
				<div class="rs-pick-code">${esc(chosen.item_code)}</div>
			</div>`;
		} else {
			html += `<div class="rs-pick-hint">${__("Pick {0} to see the price and stock", [data.attributes.map((a) => __(a)).join(" and ")])}</div>`;
		}
		$wrap.html(html);

		const blocked = chosen && chosen.is_stock_item && chosen.actual_qty <= 0 && !data.allow_negative_stock;
		dialog.get_primary_btn().prop("disabled", !chosen || chosen.rate == null || blocked);
	}

	dialog.fields_dict.picker.$wrapper.on("click", ".rs-opt", function () {
		const attr = $(this).attr("data-attr");
		const val = $(this).attr("data-val");
		if (selected[attr] === val) delete selected[attr];
		else selected[attr] = val;
		render();
	});

	// pre-select attributes that only have one possible value
	data.attributes.forEach((a) => {
		if (data.options[a].length === 1) selected[a] = data.options[a][0];
	});
	render();
	dialog.show();
};

retail_store.pos.patch = function () {
	const PS = erpnext.PointOfSale;
	if (!PS || !PS.Controller || !PS.ItemSelector) return false;
	if (PS.Controller.prototype.__rs_patched) return true;

	// ERPNext's menu offers "Open Form View" (raw Sales Invoice editing). Only managers and the
	// back office get it; a cashier reprints / returns from Recent Orders.
	const original_prepare_menu = PS.Controller.prototype.prepare_menu;
	PS.Controller.prototype.prepare_menu = function () {
		original_prepare_menu.call(this);
		if (!frappe.boot.retail_store_pos_form_view) {
			this.page.menu.find("a.dropdown-item").filter((i, a) => $(a).text().includes(__("Open Form View"))).parent().remove();
			// the Ctrl+F shortcut the menu item registered
			frappe.ui.keys.off("ctrl+f", this.page);
		}
	};

	const original_on_cart_update = PS.Controller.prototype.on_cart_update;
	PS.Controller.prototype.on_cart_update = async function (args) {
		const item = args && args.item;
		const from_selector = args && args.field === "qty" && args.value === "+1";
		if (from_selector && item && item.item_code && (await retail_store.pos.is_template(item.item_code))) {
			if (!this.frm.doc.customer) return this.raise_customer_selection_alert();
			const variant = await retail_store.pos.pick_variant(this, item.item_code);
			if (!variant) return;
			retail_store.pos.template_cache.set(variant.item_code, false);
			args = {
				...args,
				item: {
					item_code: variant.item_code,
					rate: variant.rate,
					uom: variant.stock_uom,
					stock_uom: variant.stock_uom,
				},
			};
		}
		return original_on_cart_update.call(this, args);
	};

	const original_get_item_html = PS.ItemSelector.prototype.get_item_html;
	PS.ItemSelector.prototype.get_item_html = function (item) {
		retail_store.pos.template_cache.set(item.item_code, !!item.rs_is_template);
		const html = original_get_item_html.call(this, item);
		if (!item.rs_is_template) return html;

		const $card = $(html);
		let label = __("{0} options", [item.rs_variant_count]);
		if (item.rs_price_max && item.rs_price_max !== item.price_list_rate) {
			label += ` · ${__("up to")} ${format_currency(item.rs_price_max, item.currency, 0)}`;
		}
		$card.addClass("rs-template-card");
		$card.find(".item-detail").append(`<div class="rs-variant-badge small text-muted">${frappe.utils.escape_html(label)}</div>`);
		return $card.prop("outerHTML");
	};

	PS.Controller.prototype.__rs_patched = true;
	return true;
};

// The POS bundle loads asynchronously and may finish after our require callback,
// so retry until ERPNext's classes exist. If the item grid was already drawn
// unpatched, reload it once so template cards get their "N options" badge.
retail_store.pos.ensure_patched = function (tries = 0) {
	if (retail_store.pos.patch()) {
		const selector = window.cur_pos && cur_pos.item_selector;
		if (selector && selector.$items_container && !selector.$items_container.find(".rs-variant-badge").length) {
			selector.load_items_data();
		}
		return;
	}
	if (tries < 600) setTimeout(() => retail_store.pos.ensure_patched(tries + 1), 50);
};

// Clock In / Out (HR). ERPNext's POS controller sets its own header buttons once the bundle
// has loaded (and would overwrite ours), so wait for it, then add ours next to Recent Orders.
retail_store.pos.add_clock_button = function (wrapper, tries = 0) {
	const ready = wrapper.pos && wrapper.page && wrapper.page.btn_secondary && wrapper.page.btn_secondary.is(":visible");
	if (ready) {
		const open_clock = () => frappe.set_route("store-clock");
		if (!wrapper.page.wrapper.find(".rs-clock-btn").length) {
			wrapper.page.add_button(__("Clock In / Out"), open_clock).addClass("rs-clock-btn");
		}
		return;
	}
	if (tries < 200) setTimeout(() => retail_store.pos.add_clock_button(wrapper, tries + 1), 100);
};

(function () {
	const page = frappe.pages["point-of-sale"];
	if (!page) return;
	const original_on_page_load = page.on_page_load;
	page.on_page_load = function (wrapper) {
		const result = original_on_page_load.call(this, wrapper);
		if (frappe.boot.retail_store_clock) retail_store.pos.add_clock_button(wrapper);
		retail_store.pos.ensure_patched();
		return result;
	};
	if (window.erpnext && erpnext.PointOfSale && erpnext.PointOfSale.Controller) retail_store.pos.ensure_patched();
})();
