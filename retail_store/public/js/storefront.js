// Public site: open the shop in GRID view the first time (the storefront look is designed for it).
// Webshop has no setting for this: all-products/index.js reads localStorage "product_view" and falls
// back to "List View". Seeding the key here (only when the shopper has never chosen) sets the default
// without editing the webshop app; a shopper's own list/grid choice is stored by webshop and respected.
try {
	if (!localStorage.getItem("product_view")) localStorage.setItem("product_view", "Grid View");
} catch (e) {
	/* storage blocked: webshop falls back to its own default */
}

// ---- Search: Enter filters the product grid ---------------------------------------------------------
// Webshop's search box only autocompletes (a dropdown of suggestions); pressing Enter does nothing, and
// its product query (webshop.api.get_product_filter_data) already accepts a `search` term that the page
// JS never sends. So: Enter reloads the listing with ?search=..., and every product query on the page
// carries that term. This script loads BEFORE webshop's bundle, so instead of patching its classes it
// wraps frappe.call, which is already there, and watches the DOM for the pieces webshop renders later.
(function () {
	var QUERY = "webshop.webshop.api.get_product_filter_data";
	var term = "";
	try {
		term = (new URLSearchParams(window.location.search).get("search") || "").trim();
	} catch (e) {}

	if (window.frappe && frappe.call) {
		var original = frappe.call;
		frappe.call = function (opts) {
			if (term && opts && typeof opts === "object" && opts.method === QUERY && opts.args) {
				opts.args.query_args = Object.assign({}, opts.args.query_args, { search: term });
			}
			return original.apply(this, arguments);
		};
	}

	document.addEventListener("keydown", function (e) {
		if (e.key !== "Enter" || !e.target || e.target.id !== "search-box") return;
		e.preventDefault();
		var q = e.target.value.trim();
		var url = new URL(window.location.href);
		if (q) url.searchParams.set("search", q);
		else url.searchParams.delete("search");
		url.searchParams.delete("start");
		window.location.href = url.toString();
	});

	function escapeHtml(text) {
		return text.replace(/[&<>"']/g, function (c) {
			return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
		});
	}

	// Webshop collapses the Filters panel under 768px ("collapse d-md-block") but ships no button to open it.
	function addFilterToggle() {
		var panel = document.getElementById("product-filters");
		if (!panel || document.querySelector(".rs-filter-toggle") || !panel.querySelector("input")) return;
		var btn = document.createElement("button");
		btn.type = "button";
		btn.className = "rs-filter-toggle d-md-none";
		btn.setAttribute("aria-controls", "product-filters");
		btn.setAttribute("aria-expanded", "false");
		btn.textContent = "Filters";
		btn.addEventListener("click", function () {
			var open = panel.classList.toggle("show");
			btn.setAttribute("aria-expanded", open ? "true" : "false");
			btn.textContent = open ? "Hide filters" : "Filters";
		});
		panel.parentNode.insertBefore(btn, panel);
	}

	function enhance() {
		addFilterToggle();
		var box = document.getElementById("search-box");
		if (box && term && !box.dataset.rsSearch) {
			box.dataset.rsSearch = "1";
			box.value = term;
		}
		var empty = document.querySelector("#product-listing .cart-empty:not(.rs-noresults)");
		if (empty) {
			var base = window.location.pathname;
			empty.className = "rs-noresults";
			empty.innerHTML = term
				? '<h2>No results for “' + escapeHtml(term) + '”</h2>' +
				  "<p>Check the spelling, or try a shorter or more general word.</p>" +
				  '<a class="rs-noresults-btn" href="' + base + '">Clear search</a> ' +
				  '<a class="rs-noresults-btn rs-alt" href="/all-products">Browse all products</a>'
				: "<h2>Nothing here yet</h2><p>No products match these filters.</p>" +
				  '<a class="rs-noresults-btn" href="/all-products">Browse all products</a>';
		}
	}

	new MutationObserver(enhance).observe(document.documentElement, { childList: true, subtree: true });
})();

// ---- Order page: say plainly that the order is placed, and what happens next ----------------------------
// Webshop's order page shows only a document number and an ERP status ("To Deliver and Bill"), with a
// generic "Actions" menu; after checkout a shopper cannot tell the order went through. This adds a
// confirmation panel, shop-language status text, and a Print button. `rs-pay-offline` is put on <body>
// by storefront.hide_pay_link_for_offline_gateway while "Pay in Store or on Delivery" is the gateway.
(function () {
	var STATUS = {
		"To Deliver and Bill": ["Order received", "We have your order and are getting it ready."],
		"To Deliver": ["Paid, getting ready", "Your payment is in. We are getting your order ready."],
		"To Bill": ["Delivered", "Your order has been handed over."],
		Completed: ["Completed", "Thank you for shopping with us."],
		Cancelled: ["Cancelled", "This order was cancelled."],
		Closed: ["Closed", "This order is closed."],
		Draft: ["Received", "We have your order and are getting it ready."],
		"On Hold": ["On hold", "We have paused this order. Contact the store if you have questions."],
	};

	function enhanceOrder() {
		if (!/^\/orders\/[^/]+$/.test(window.location.pathname)) return;
		var pill = document.querySelector(".indicator-container .indicator-pill");
		var content = document.querySelector(".page-content, .order-container");
		if (!pill || !content || document.querySelector(".rs-order-status")) return;
		var raw = pill.textContent.trim();
		var info = STATUS[raw];
		if (!info) return;
		var offline = document.body.classList.contains("rs-pay-offline");
		var unpaid = raw === "To Deliver and Bill" || raw === "To Bill" || raw === "Draft";
		var next = "";
		if (raw === "Cancelled" || raw === "Closed") next = "";
		else if (offline && unpaid) next = "Nothing has been charged online. <b>Pay in store when you collect it, or on delivery.</b>";
		else if (unpaid) next = "Payment is still due for this order.";
		var panel = document.createElement("div");
		panel.className = "rs-order-status" + (raw === "Cancelled" ? " rs-cancelled" : "");
		panel.innerHTML =
			'<div class="rs-order-tick" aria-hidden="true">' + (raw === "Cancelled" ? "!" : "✓") + "</div>" +
			"<div><h2>" + info[0] + "</h2><p>" + info[1] + "</p>" + (next ? "<p>" + next + "</p>" : "") + "</div>";
		var anchor = document.querySelector(".indicator-container");
		anchor.parentNode.insertBefore(panel, anchor);
		pill.style.display = "none"; // the panel above says it

		// "Actions" held one item (Print) behind a menu; show it as a button
		var menu = document.querySelector(".page-header .dropdown, .page-head .dropdown, .dropdown-menu-right");
		var print = document.querySelector('a.dropdown-item[href^="/printview"]');
		if (print) {
			var btn = document.createElement("a");
			btn.className = "rs-order-print";
			btn.href = print.getAttribute("href");
			btn.target = "_blank";
			btn.rel = "noopener noreferrer";
			btn.textContent = "Print receipt";
			var dd = print.closest(".dropdown");
			if (dd) dd.replaceWith(btn);
		}
	}
	new MutationObserver(enhanceOrder).observe(document.documentElement, { childList: true, subtree: true });
	document.addEventListener("DOMContentLoaded", enhanceOrder);
})();

// ---- Shopper account pages: shop wording instead of ERPNext terms --------------------------------------
// The portal sidebar, order list, empty cart and /me page are webshop / Frappe pages with ERP words
// (Quotations, Invoices, Shipments, "To Deliver and Bill", "Manage 3rd party apps"). Server-rendered,
// so they are reworded here once the page is in the DOM. Pages themselves and their permissions are untouched.
(function () {
	var NAV = { "/invoices": "Receipts", "/shipments": "Deliveries" };
	var HIDE_NAV = ["/quotations"]; // a shopper's "quotations" are just past carts; nothing to act on
	var LIST_STATUS = {
		"To Deliver and Bill": "Order received",
		"To Deliver": "Paid, getting ready",
		"To Bill": "Delivered",
		Completed: "Completed",
		Cancelled: "Cancelled",
		Closed: "Closed",
		Draft: "Received",
		"On Hold": "On hold",
	};
	var path = window.location.pathname.replace(/\/$/, "");

	function guest() {
		return !(window.frappe && frappe.session && frappe.session.user && frappe.session.user !== "Guest");
	}

	function reword() {
		document.querySelectorAll("a[href]").forEach(function (a) {
			var href = (a.getAttribute("href") || "").replace(/\/$/, "");
			if (HIDE_NAV.indexOf(href) !== -1 && (a.closest(".sidebar-item") || a.classList.contains("nav-link") || a.closest(".list-sidebar, .sidebar-column"))) {
				var holder = a.closest("li, .sidebar-item") || a;
				holder.style.display = "none";
			} else if (NAV[href] && !a.dataset.rsWorded && (a.closest(".sidebar-item") || a.classList.contains("nav-link") || a.closest(".list-sidebar, .sidebar-column"))) {
				a.dataset.rsWorded = "1";
				a.textContent = NAV[href];
			}
		});
		if (path === "/orders" || path === "/invoices") {
			document.querySelectorAll(".indicator-pill.list-item-status, .list-item-status").forEach(function (pill) {
				var word = LIST_STATUS[pill.textContent.trim()];
				if (word) pill.textContent = word;
			});
		}
		if (path === "/invoices") {
			document.querySelectorAll("h1, .page-title, .portal-head h3").forEach(function (h) {
				if (h.textContent.trim() === "Invoices") h.textContent = "Receipts";
			});
		}
		if (path === "/shipments") {
			document.querySelectorAll("h1, .page-title, .portal-head h3").forEach(function (h) {
				if (h.textContent.trim() === "Shipments") h.textContent = "Deliveries";
			});
		}
		if (path === "/addresses") {
			var nothing = Array.prototype.find.call(document.querySelectorAll("body div"), function (e) {
				return e.children.length === 0 && e.textContent.trim() === "Nothing to show";
			});
			if (nothing) nothing.textContent = "No saved addresses yet. You can add one when you check out.";
		}
		// empty cart: say what to do next; "See past orders" only makes sense for someone who has ordered
		var msg = document.querySelector(".cart-empty .cart-empty-message");
		if (msg && !msg.dataset.rsWorded) {
			msg.dataset.rsWorded = "1";
			var box = msg.closest(".cart-empty");
			var old = box.querySelector("a.btn");
			if (old) old.remove();
			msg.textContent = "Your cart is empty";
			var note = document.createElement("p");
			note.className = "rs-cart-empty-note";
			note.textContent = guest() ? "Browse the shop and add what you like. You only need to log in when you check out." : "Browse the shop and add what you like.";
			var actions = document.createElement("div");
			actions.className = "rs-cart-empty-actions";
			actions.innerHTML = '<a class="btn btn-primary" href="/all-products">Start shopping</a>' + (guest() ? "" : '<a class="btn btn-outline-primary" href="/orders">See past orders</a>');
			msg.after(note, actions);
		}
		// /me: Frappe's technical entries mean nothing to a shopper
		if (path === "/me") {
			document.body.classList.add("rs-me");
			document.querySelectorAll('a[href="/third_party_apps"], a[href="/portal"]').forEach(function (a) {
				var hide = a;  // take the wrapper too, or an empty bordered row is left behind
				while (hide.parentElement && hide.parentElement.children.length === 1 && !hide.parentElement.matches("main, body, .page-content")) hide = hide.parentElement;
				hide.classList.add("rs-me-hidden");
			});
		}
	}
	new MutationObserver(reword).observe(document.documentElement, { childList: true, subtree: true });
	document.addEventListener("DOMContentLoaded", reword);
})();
