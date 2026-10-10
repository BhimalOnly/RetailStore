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
