// Retail Store home page: a colour + icon badge on each shortcut and group card, and an icon beside the
// section headings. Frappe draws these cards itself and gives shortcuts no icon, so this adds them after
// the fact. Keyed on the English card titles: a card with an unknown title simply gets no badge.
(function () {
	const MODULES = {
		"Point of Sale": ["teal", "monitor"], Sales: ["teal", "receipt"], Selling: ["teal", "shopping-cart"],
		Customer: ["rose", "users"], Loyalty: ["rose", "gift"],
		Products: ["violet", "tag"], Catalogue: ["violet", "tags"],
		"Stock Levels": ["amber", "boxes"], "Request Transfer": ["amber", "repeat"], "Move Stock": ["amber", "truck"], Stock: ["amber", "package"],
		Reports: ["blue", "trending-up"], Setup: ["slate", "settings"],
	};
	const HEADINGS = { today: "sun", "everything else": "layout-grid" };
	const icon = (name) => `<svg class="icon"><use href="#icon-${name}"></use></svg>`;

	function decorate() {
		if (document.body.getAttribute("data-route") !== "Workspaces/Retail Store") return;
		document.querySelectorAll(".editor-js-container .shortcut-widget-box, .editor-js-container .links-widget-box").forEach((w) => {
			if (w.querySelector(".rs-badge")) return;
			const title = w.querySelector(".widget-title");
			const m = title && MODULES[title.textContent.trim()];
			if (!m) return;
			w.classList.add("rs-m-" + m[0]);
			const badge = document.createElement("span");
			badge.className = "rs-badge";
			badge.innerHTML = icon(m[1]);
			w.querySelector(".widget-head").prepend(badge);
		});
		document.querySelectorAll(".editor-js-container .ce-header .h4").forEach((h) => {
			const name = HEADINGS[h.textContent.trim().toLowerCase()];
			if (name && !h.querySelector("svg")) h.insertAdjacentHTML("afterbegin", icon(name));
		});
	}

	let timer;
	new MutationObserver(() => {
		clearTimeout(timer);
		timer = setTimeout(decorate, 60);
	}).observe(document.documentElement, { childList: true, subtree: true });
})();
