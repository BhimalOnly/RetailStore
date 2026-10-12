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

	// ---- Closing a shift ------------------------------------------------------------------------------
	// Why the shift is being closed decides where the cashier lands afterwards (public/js/pos_closing_entry.js):
	// "end" = they chose Close the POS (end of day) -> Retail Store home; "stale" = an earlier day's shift was in
	// the way of selling -> straight back into POS to open today's. The closing form reads this flag.
	const original_close_pos = PS.Controller.prototype.close_pos;
	PS.Controller.prototype.close_pos = function () {
		retail_store.pos.set_close_reason("end");
		return original_close_pos.apply(this, arguments);
	};

	// ERPNext shows a dismissable yellow note when the open shift is from an earlier day, and the cashier can
	// carry on selling into it (two days' cash in one count). Replace it with a dialog that cannot be closed,
	// whose one action is to close that shift.
	PS.Controller.prototype.check_outdated_pos_opening_entry = function () {
		if (!frappe.datetime.get_day_diff(frappe.datetime.get_today(), (this.pos_opening_time || "").slice(0, 10))) return;
		const me = this;
		const opened = frappe.datetime.str_to_user((this.pos_opening_time || "").slice(0, 10));
		const dialog = new frappe.ui.Dialog({
			title: __("An earlier shift is still open"),
			static: true,
			fields: [
				{
					fieldtype: "HTML",
					options: `<div class="rs-stale-shift"><p>${__("This till was opened on {0} and was never closed.", [`<b>${frappe.utils.escape_html(opened)}</b>`])}</p>
						<p>${__("Close that shift first, so each day's cash is counted on its own. You will come straight back here to open today's shift.")}</p></div>`,
				},
			],
			primary_action_label: __("Close shift"),
			primary_action() {
				retail_store.pos.set_close_reason("stale");
				const voucher = frappe.model.get_new_doc("POS Closing Entry");
				voucher.pos_profile = me.pos_profile;
				voucher.user = frappe.session.user;
				voucher.company = me.company;
				voucher.pos_opening_entry = me.pos_opening;
				voucher.period_end_date = frappe.datetime.now_datetime();
				voucher.posting_date = frappe.datetime.now_date();
				voucher.posting_time = frappe.datetime.now_time();
				dialog.hide();
				frappe.set_route("Form", "POS Closing Entry", voucher.name);
			},
			secondary_action_label: __("Back to Retail Store"),
			secondary_action() {
				dialog.hide();
				frappe.set_route("retail-store");
			},
		});
		dialog.$wrapper.addClass("rs-stale-dialog");
		dialog.show();
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

retail_store.pos.set_close_reason = function (reason) {
	try {
		sessionStorage.setItem("rs_close_reason", reason);
	} catch (e) {
		/* storage blocked: the closing form then simply stays where it is */
	}
};

// "‹ Retail Store": the way out of POS. The only other exit is the toolbar's small home icon, which nobody on a
// till should have to know about. An unpaid cart asks first, so a sale in progress is not lost by a stray tap.
retail_store.pos.add_back_button = function (wrapper, tries = 0) {
	const $head = wrapper.page && wrapper.page.wrapper && wrapper.page.wrapper.find(".page-head .title-area, .page-head .page-title").first();
	if ($head && $head.length) {
		if (wrapper.page.wrapper.find(".rs-pos-back").length) return;
		const $back = $(`<button type="button" class="rs-pos-back" title="${__("Back to Retail Store")}">&lsaquo; ${__("Retail Store")}</button>`);
		$back.on("click", () => {
			const items = (window.cur_pos && cur_pos.frm && cur_pos.frm.doc && cur_pos.frm.doc.items) || [];
			if (items.length) {
				frappe.confirm(__("Leave this sale? The items in the cart have not been paid for."), () => frappe.set_route("retail-store"));
			} else {
				frappe.set_route("retail-store");
			}
		});
		$head.prepend($back);
		return;
	}
	if (tries < 100) setTimeout(() => retail_store.pos.add_back_button(wrapper, tries + 1), 100);
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
		retail_store.pos.add_back_button(wrapper);
		if (frappe.boot.retail_store_clock) retail_store.pos.add_clock_button(wrapper);
		retail_store.pos.ensure_patched();
		return result;
	};
	if (window.erpnext && erpnext.PointOfSale && erpnext.PointOfSale.Controller) retail_store.pos.ensure_patched();
})();
