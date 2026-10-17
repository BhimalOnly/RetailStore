// Storefront shopping UI: variant swatches on product cards, a quick-view modal, and a slide-over
// cart drawer. Everything real goes through Webshop's own endpoints, nothing is re-implemented:
//   cart:      webshop.webshop.shopping_cart.cart.update_cart / get_cart_quotation
//   variants:  webshop.webshop.variant_selector.utils.get_next_attribute_and_values
//              (exact variant, its price, stock) and, for a page of cards in one call,
//              retail_store.storefront.get_card_variants (wraps get_attributes_and_values)
// This file loads BEFORE Webshop's bundle, so it wraps frappe.call (already present) to learn about
// the products a listing returns and to notice a successful Add to Cart, and looks the rest up at
// click time.
(function () {
	"use strict";

	var LISTING = "webshop.webshop.api.get_product_filter_data";
	var UPDATE = "webshop.webshop.shopping_cart.cart.update_cart";
	var CART = "webshop.webshop.shopping_cart.cart.get_cart_quotation";
	var NEXT = "webshop.webshop.variant_selector.utils.get_next_attribute_and_values";
	var CARD_VARIANTS = "retail_store.storefront.get_card_variants";
	var MAX_CHIPS = 5;
	var CSS_WIDE = ["inherit", "initial", "unset", "revert", "revert-layer", "transparent", "currentcolor"];

	var items = {}; // route -> product from the listing
	var options = {}; // item_code -> [{attribute, values}]
	var onCartPage = /^\/cart(\/|$)/.test(window.location.pathname);

	function esc(text) {
		return String(text == null ? "" : text).replace(/[&<>"']/g, function (c) {
			return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
		});
	}
	function money(value, currency) {
		try {
			return format_currency(value, currency);
		} catch (e) {
			return String(value);
		}
	}
	function isColour(value) {
		var v = String(value).trim().toLowerCase();
		return !!(window.CSS && CSS.supports && CSS.supports("color", v) && CSS_WIDE.indexOf(v) < 0);
	}

	// ---------------------------------------------------------------------------------------------
	// frappe.call wrapper
	// ---------------------------------------------------------------------------------------------
	var original = frappe.call;
	frappe.call = function (opts) {
		if (opts && typeof opts === "object") {
			if (opts.method === LISTING) {
				var done = opts.callback;
				opts.callback = function (r) {
					if (done) done.apply(this, arguments);
					try {
						learn(r);
					} catch (e) {
						if (window.console) console.error(e);
					}
				};
			} else if (opts.method === UPDATE && !onCartPage) {
				var after = opts.callback;
				var qty = parseFloat(opts.args && opts.args.qty);
				opts.callback = function (r) {
					if (after) after.apply(this, arguments);
					if (!r.exc && qty > 0) drawer.open();
				};
			}
		}
		return original.apply(this, arguments);
	};

	// ---------------------------------------------------------------------------------------------
	// product cards: Quick view button + swatches
	// ---------------------------------------------------------------------------------------------
	function learn(r) {
		var list = r && r.message && r.message.items;
		if (!list) return;
		list.forEach(function (item) {
			if (item.route) items[item.route] = item;
		});
		var need = list.filter(function (i) { return i.has_variants && !options[i.item_code]; }).map(function (i) { return i.item_code; });
		decorate();
		if (!need.length) return;
		original.call(frappe, {
			method: CARD_VARIANTS,
			args: { item_codes: JSON.stringify(need) },
			callback: function (res) {
				var data = (res && res.message) || {};
				need.forEach(function (code) { options[code] = data[code] || []; });
				decorate();
			},
		});
	}

	function routeOf(card) {
		var a = card.querySelector("a[href]");
		return a ? a.getAttribute("href").replace(/^\//, "") : null;
	}

	function decorate() {
		document.querySelectorAll(".item-card").forEach(function (card) {
			var item = items[routeOf(card)];
			if (!item) return;
			if (!card.querySelector(".rs-qv-btn")) {
				var box = card.querySelector(".card-img-container");
				if (box) {
					var b = document.createElement("button");
					b.type = "button";
					b.className = "rs-qv-btn";
					b.textContent = "Quick view";
					b.setAttribute("aria-label", "Quick view: " + (item.web_item_name || item.item_name));
					b.addEventListener("click", function (e) {
						e.preventDefault();
						e.stopPropagation();
						quick.open(item, {}, b);
					});
					box.appendChild(b);
				}
			}
			var opts = options[item.item_code];
			if (item.has_variants && opts && opts.length && !card.querySelector(".rs-swatches")) {
				var wrap = document.createElement("div");
				wrap.className = "rs-swatches";
				opts.forEach(function (o) {
					var row = document.createElement("div");
					row.className = "rs-sw-row";
					var colours = o.values.every(isColour);
					var shown = colours ? o.values : o.values.slice(0, MAX_CHIPS);
					shown.forEach(function (v) {
						var s = document.createElement("button");
						s.type = "button";
						s.dataset.attr = o.attribute;
						s.dataset.val = v;
						s.title = v;
						s.setAttribute("aria-label", o.attribute + ": " + v);
						if (colours) {
							s.className = "rs-sw rs-sw-colour";
							s.style.setProperty("--c", v.toLowerCase());
						} else {
							s.className = "rs-sw rs-sw-chip";
							s.textContent = v;
						}
						s.addEventListener("click", function (e) {
							e.preventDefault();
							var pick = {};
							pick[o.attribute] = v;
							quick.open(item, pick, s);
						});
						row.appendChild(s);
					});
					if (shown.length < o.values.length) {
						var more = document.createElement("span");
						more.className = "rs-sw-more";
						more.textContent = "+" + (o.values.length - shown.length);
						row.appendChild(more);
					}
					wrap.appendChild(row);
				});
				var anchor = card.querySelector(".product-category");
				if (anchor) anchor.insertAdjacentElement("afterend", wrap);
			}
		});
	}

	// ---------------------------------------------------------------------------------------------
	// shared overlay + modal plumbing
	// ---------------------------------------------------------------------------------------------
	var overlay;
	function ensureOverlay() {
		if (overlay) return overlay;
		overlay = document.createElement("div");
		overlay.className = "rs-overlay";
		overlay.hidden = true;
		overlay.addEventListener("click", function () {
			quick.close();
			drawer.close();
		});
		document.body.appendChild(overlay);
		return overlay;
	}
	function lock(on) {
		document.documentElement.classList.toggle("rs-lock", on);
		ensureOverlay().hidden = !on;
	}
	document.addEventListener("keydown", function (e) {
		if (e.key === "Escape") {
			quick.close();
			drawer.close();
		}
	});

	// quantity stepper + Add to cart, shared by the quick-view modal and the product-page picker
	function wireActions(el, picker) {
		el.querySelectorAll(".rs-qty button").forEach(function (b) {
			b.addEventListener("click", function () {
				var n = el.querySelector(".rs-qty-n");
				n.textContent = Math.max(1, Math.min(99, parseInt(n.textContent, 10) + parseInt(b.dataset.d, 10)));
			});
		});
		el.querySelector(".rs-add").addEventListener("click", function () { picker.add(this); });
	}


	// ---------------------------------------------------------------------------------------------
	// quick view
	// ---------------------------------------------------------------------------------------------
	var quick = {
		el: null,
		state: null,
		opener: null,

		build: function () {
			if (this.el) return;
			var el = document.createElement("div");
			el.className = "rs-qv";
			el.setAttribute("role", "dialog");
			el.setAttribute("aria-modal", "true");
			el.setAttribute("aria-label", "Quick view");
			el.hidden = true;
			el.innerHTML =
				'<button type="button" class="rs-x" aria-label="Close">&times;</button>' +
				'<div class="rs-qv-img"></div>' +
				'<div class="rs-qv-body">' +
				'<div class="rs-qv-cat"></div><h2 class="rs-qv-title"></h2>' +
				'<div class="rs-qv-price"></div><div class="rs-qv-stock"></div>' +
				'<div class="rs-qv-opts"></div>' +
				'<div class="rs-qv-actions">' +
				'<div class="rs-qty"><button type="button" data-d="-1" aria-label="Fewer">&minus;</button><span class="rs-qty-n">1</span><button type="button" data-d="1" aria-label="More">+</button></div>' +
				'<button type="button" class="rs-add">Add to cart</button></div>' +
				'<a class="rs-qv-more" href="#">View full details</a></div>';
			document.body.appendChild(el);
			var me = this;
			el.querySelector(".rs-x").addEventListener("click", function () { me.close(); });
			wireActions(el, me);
			this.el = el;
		},

		open: function (item, preselect, opener) {
			this.build();
			this.opener = opener || null;
			this.state = { item: item, selected: Object.assign({}, preselect), exact: null, price: null, out: false, valid: null };
			var el = this.el;
			var image = item.website_image;
			el.querySelector(".rs-qv-img").innerHTML = image
				? '<img src="' + esc(image) + '" alt="' + esc(item.web_item_name || item.item_name) + '">'
				: '<div class="rs-qv-noimg">' + esc(frappe.get_abbr(item.web_item_name || item.item_name || "")) + "</div>";
			el.querySelector(".rs-qv-cat").textContent = item.item_group || "";
			el.querySelector(".rs-qv-title").textContent = item.web_item_name || item.item_name || item.item_code;
			el.querySelector(".rs-qv-more").setAttribute("href", "/" + item.route);
			el.querySelector(".rs-qty-n").textContent = "1";
			this.renderOptions();
			this.refresh();
			el.hidden = false;
			lock(true);
			el.querySelector(".rs-x").focus();
		},

		close: function () {
			if (!this.el || this.el.hidden) return;
			this.el.hidden = true;
			if (!drawer.isOpen()) lock(false);
			if (this.opener && this.opener.focus) this.opener.focus();
		},

		renderOptions: function () {
			var st = this.state;
			var box = this.el.querySelector(".rs-qv-opts");
			var opts = st.item.has_variants ? options[st.item.item_code] : null;
			if (st.item.has_variants && !opts) {
				box.innerHTML = '<div class="rs-qv-wait">Loading options…</div>';
				var me = this;
				original.call(frappe, {
					method: CARD_VARIANTS,
					args: { item_codes: JSON.stringify([st.item.item_code]) },
					callback: function (res) {
						options[st.item.item_code] = ((res && res.message) || {})[st.item.item_code] || [];
						if (me.state === st) {
							me.renderOptions();
							me.refresh();
						}
					},
				});
				return;
			}
			if (!opts || !opts.length) {
				box.innerHTML = "";
				return;
			}
			var html = "";
			opts.forEach(function (o) {
				var colours = o.values.every(isColour);
				html += '<div class="rs-opt" data-attr="' + esc(o.attribute) + '"><div class="rs-opt-label">' + esc(o.attribute.replace(/^DEMO /, "")) + ': <b class="rs-opt-val"></b></div><div class="rs-opt-vals">';
				o.values.forEach(function (v) {
					html += colours
						? '<button type="button" class="rs-sw rs-sw-colour" data-val="' + esc(v) + '" title="' + esc(v) + '" aria-label="' + esc(o.attribute + ": " + v) + '" style="--c:' + esc(v.toLowerCase()) + '"></button>'
						: '<button type="button" class="rs-sw rs-sw-chip" data-val="' + esc(v) + '">' + esc(v) + "</button>";
				});
				html += "</div></div>";
			});
			box.innerHTML = html;
			var me2 = this;
			box.querySelectorAll(".rs-sw").forEach(function (b) {
				b.addEventListener("click", function () {
					if (b.disabled) return;
					var attr = b.closest(".rs-opt").dataset.attr;
					if (me2.state.selected[attr] === b.dataset.val) delete me2.state.selected[attr];
					else me2.state.selected[attr] = b.dataset.val;
					me2.refresh();
				});
			});
		},

		// ask Webshop which variant the current choice is, and what it costs / has in stock
		refresh: function () {
			var st = this.state;
			var me = this;
			var item = st.item;
			if (!item.has_variants) {
				st.exact = item.item_code;
				st.price = item.formatted_price || null;
				// webshop sends in_stock as a boolean
				st.out = item.in_stock !== undefined && !item.in_stock && !item.on_backorder;
				this.paint();
				return;
			}
			st.exact = null;
			st.price = null;
			st.out = false;
			st.valid = null;
			st.none = false;
			if (!Object.keys(st.selected).length) {
				this.paint();
				return;
			}
			original.call(frappe, {
				method: NEXT,
				args: { item_code: item.item_code, selected_attributes: JSON.stringify(st.selected) },
				callback: function (r) {
					if (me.state !== st || !r.message) return;
					var m = r.message;
					st.valid = m.valid_options_for_attributes || {};
					st.none = !m.filtered_items_count;
					if (m.exact_match && m.exact_match.length === 1) {
						st.exact = m.exact_match[0];
						var info = m.product_info || {};
						st.price = info.price ? info.price.formatted_price || null : null;
						st.qty = parseFloat(m.available_qty) || 0;
						st.out = !!(info.is_stock_item && !info.allow_items_not_in_stock && !(st.qty > 0));
					}
					me.paint();
				},
			});
		},

		paint: function () {
			var st = this.state;
			var el = this.el;
			el.querySelectorAll(".rs-opt").forEach(function (row) {
				var attr = row.dataset.attr;
				row.querySelector(".rs-opt-val").textContent = st.selected[attr] || "";
				row.querySelectorAll(".rs-sw").forEach(function (b) {
					var on = st.selected[attr] === b.dataset.val;
					b.classList.toggle("is-on", on);
					b.setAttribute("aria-pressed", on ? "true" : "false");
					// values that no variant offers together with the other choices are greyed out
					var okSet = st.valid && !(attr in st.selected) ? st.valid[attr] : null;
					b.disabled = !!(okSet && okSet.indexOf(b.dataset.val) < 0);
				});
			});
			var price = el.querySelector(".rs-qv-price");
			price.innerHTML = st.price ? esc(st.price) : st.item.has_variants && !st.exact ? '<span class="rs-muted">Choose options to see the price</span>' : "";
			var stock = el.querySelector(".rs-qv-stock");
			stock.textContent = st.out ? "Out of stock" : st.none ? "This combination is not available" : st.exact && (st.item.has_variants ? st.qty > 0 : !!st.item.in_stock) ? "In stock" : "";
			stock.className = "rs-qv-stock" + (st.out || st.none ? " is-bad" : "");
			var add = el.querySelector(".rs-add");
			add.disabled = !st.exact || st.out;
			add.textContent = st.out ? "Out of stock" : st.item.has_variants && !st.exact ? "Select options" : "Add to cart";
		},

		add: function (btn) {
			var st = this.state;
			if (!st || !st.exact || st.out) return;
			var me = this;
			var qty = parseInt(this.el.querySelector(".rs-qty-n").textContent, 10) || 1;
			window.webshop.webshop.shopping_cart.update_cart({
				item_code: st.exact,
				qty: qty,
				btn: btn,
				callback: function (r) {
					if (!r.exc) me.close();
				},
			});
		},
	};

	// ---------------------------------------------------------------------------------------------
	// cart drawer
	// ---------------------------------------------------------------------------------------------
	var drawer = {
		el: null,
		busy: false,

		isOpen: function () {
			return !!(this.el && !this.el.hidden);
		},

		build: function () {
			if (this.el) return;
			var el = document.createElement("aside");
			el.className = "rs-drawer";
			el.setAttribute("role", "dialog");
			el.setAttribute("aria-modal", "true");
			el.setAttribute("aria-label", "Shopping cart");
			el.hidden = true;
			el.innerHTML =
				'<header class="rs-drawer-head"><h2>Your cart <span class="rs-drawer-count"></span></h2><button type="button" class="rs-x" aria-label="Close cart">&times;</button></header>' +
				'<div class="rs-drawer-items" aria-live="polite"></div>' +
				'<footer class="rs-drawer-foot"><div class="rs-sub"><span>Subtotal</span><b class="rs-sub-amt"></b></div>' +
				'<a class="rs-btn" href="/cart">Checkout</a><a class="rs-btn rs-alt" href="/cart">View cart</a></footer>';
			document.body.appendChild(el);
			var me = this;
			el.querySelector(".rs-x").addEventListener("click", function () { me.close(); });
			el.addEventListener("click", function (e) {
				var b = e.target.closest("button[data-act]");
				if (!b) return;
				me.change(b.dataset.code, b.dataset.act, parseFloat(b.dataset.qty));
			});
			this.el = el;
		},

		open: function () {
			if (onCartPage) return;
			this.build();
			quick.close();
			this.el.hidden = false;
			lock(true);
			this.load();
			this.el.querySelector(".rs-x").focus();
		},

		close: function () {
			if (!this.el || this.el.hidden) return;
			this.el.hidden = true;
			if (!quick.el || quick.el.hidden) lock(false);
		},

		load: function () {
			var me = this;
			original.call(frappe, {
				method: CART,
				callback: function (r) {
					if (r.message) me.render(r.message.doc, r.message.formatted);
				},
			});
		},

		render: function (doc, formatted) {
			formatted = formatted || { lines: {} };
			var box = this.el.querySelector(".rs-drawer-items");
			var lines = (doc && doc.items) || [];
			var count = lines.reduce(function (n, d) { return n + (parseFloat(d.qty) || 0); }, 0);
			this.el.querySelector(".rs-drawer-count").textContent = count ? "(" + count + ")" : "";
			this.el.classList.toggle("is-empty", !lines.length);
			if (!lines.length) {
				box.innerHTML = '<div class="rs-drawer-empty"><p>Your cart is empty.</p><button type="button" class="rs-btn rs-close-btn">Continue shopping</button></div>';
				var me = this;
				box.querySelector(".rs-close-btn").addEventListener("click", function () { me.close(); });
				return;
			}
			var html = "";
			lines.forEach(function (d) {
				var name = d.web_item_name || d.item_name || d.item_code;
				var img = d.thumbnail || d.website_image || d.image;
				var link = d.route ? "/" + d.route : "#";
				html +=
					'<div class="rs-line" data-code="' + esc(d.item_code) + '">' +
					'<a class="rs-line-img" href="' + esc(link) + '">' + (img ? '<img src="' + esc(img) + '" alt="">' : "<span>" + esc(frappe.get_abbr(name)) + "</span>") + "</a>" +
					'<div class="rs-line-main"><a class="rs-line-name" href="' + esc(link) + '">' + esc(name) + "</a>" +
					'<div class="rs-line-code">' + esc(d.item_code) + "</div>" +
					'<div class="rs-line-row"><div class="rs-qty">' +
					'<button type="button" data-act="set" data-code="' + esc(d.item_code) + '" data-qty="' + (d.qty - 1) + '" aria-label="Fewer">&minus;</button><span class="rs-qty-n">' + esc(d.qty) + "</span>" +
					'<button type="button" data-act="set" data-code="' + esc(d.item_code) + '" data-qty="' + (parseFloat(d.qty) + 1) + '" aria-label="More">+</button></div>' +
					'<b class="rs-line-amt">' + esc((formatted.lines[d.item_code] || {}).amount || money(d.amount, doc.currency)) + "</b></div></div>" +
					'<button type="button" class="rs-line-x" data-act="set" data-code="' + esc(d.item_code) + '" data-qty="0" aria-label="Remove ' + esc(name) + '">&times;</button></div>';
			});
			box.innerHTML = html;
			this.el.querySelector(".rs-sub-amt").textContent = formatted.total || money(doc.total, doc.currency);
		},

		change: function (code, act, qty) {
			var me = this;
			if (this.busy) return;
			this.busy = true;
			original.call(frappe, {
				type: "POST",
				method: UPDATE,
				args: { item_code: code, qty: qty },
				callback: function (r) {
					me.busy = false;
					if (r.exc) return;
					try {
						window.webshop.webshop.shopping_cart.set_cart_count(true);
					} catch (e) {}
					me.load();
				},
				error: function () {
					me.busy = false;
				},
			});
		},
	};

	// the navbar cart icon opens the drawer instead of navigating (everywhere except the cart page)
	document.addEventListener(
		"click",
		function (e) {
			if (onCartPage || frappe.session.user === "Guest") return;
			var a = e.target.closest && e.target.closest("li.shopping-cart a, .shopping-cart > a");
			if (!a) return;
			e.preventDefault();
			e.stopPropagation();
			drawer.open();
		},
		true
	);

	// ---------------------------------------------------------------------------------------------
	// product page: the same option picker, inline instead of Webshop's "Select Variant" dialog.
	// Inherits quick's renderOptions / refresh / paint / add; only the container differs.
	// ---------------------------------------------------------------------------------------------
	var pdp = Object.create(quick);
	pdp.el = null;
	pdp.state = null;
	pdp.close = function () {}; // nothing to dismiss; the cart drawer opens after a successful add

	pdp.mount = function () {
		var trigger = document.querySelector(".btn-configure");
		if (!trigger || this.el) return;
		var code = trigger.dataset.itemCode;
		var name = trigger.dataset.itemName || code;
		var el = document.createElement("div");
		el.className = "rs-pdp-picker";
		el.innerHTML =
			'<div class="rs-qv-price"></div><div class="rs-qv-stock"></div>' +
			'<div class="rs-qv-opts"></div>' +
			'<div class="rs-qv-actions">' +
			'<div class="rs-qty"><button type="button" data-d="-1" aria-label="Fewer">&minus;</button><span class="rs-qty-n">1</span><button type="button" data-d="1" aria-label="More">+</button></div>' +
			'<button type="button" class="rs-add">Add to cart</button></div>';
		trigger.insertAdjacentElement("afterend", el);
		trigger.style.display = "none";
		wireActions(el, this);
		this.el = el;
		this.state = { item: { item_code: code, item_name: name, web_item_name: name, has_variants: true }, selected: {}, exact: null, price: null, out: false, valid: null };
		this.renderOptions();
		this.refresh();
	};

	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { pdp.mount(); });
	else pdp.mount();

	window.RS = { quick: quick, pdp: pdp, drawer: drawer, items: items, options: options };
})();
