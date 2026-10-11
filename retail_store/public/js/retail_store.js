// Applies per-site brand colours from Retail Store Settings as CSS variables.
// Deliberately tiny: no stylesheet, no DOM rewrites, so a Desk theme app can coexist.
// App names and version numbers (the avatar menu's "Installed Apps", Frappe's error-report dialog) are for
// System Manager. Frappe fills boot.versions AFTER the server's boot hooks, so it is emptied here, before
// anything reads it. (get_versions, the API behind the About dialog, is wrapped in navigation.py.)
(function () {
	const roles = (frappe.boot && frappe.boot.user && frappe.boot.user.roles) || [];
	if (frappe.boot && roles.length && roles.indexOf("System Manager") === -1) frappe.boot.versions = {};
})();

(function () {
	function apply(branding) {
		if (!branding) return;
		const root = document.documentElement.style;
		if (branding.brand_color) root.setProperty("--rs-brand", branding.brand_color);
		if (branding.accent_color) root.setProperty("--rs-accent", branding.accent_color);
		if (branding.apply_to_desk && branding.brand_color) {
			root.setProperty("--primary", branding.brand_color);
			root.setProperty("--primary-color", branding.brand_color);
			root.setProperty("--btn-primary", branding.brand_color);
		}
	}

	// the Desk theme's "Powered by" credit is for the people who run the system, not shop staff
	function hideCredit() {
		if (frappe.user && frappe.user.has_role && frappe.user.has_role("System Manager")) return;
		if (document.getElementById("rs-no-credit")) return;
		// the rail's top tile repeats the Retail Store app icon right under it (and used to open Frappe's home);
		// Reset Desktop Layout, the workspace search/list (one entry) and the theme-profile picker (names Frappe/Solvronix)
		// in All Options mean nothing to shop staff: Appearance (theme, density, font size) stays
		$('<style id="rs-no-credit">#st-powered-by,#st-icon-rail .st-rail-brand,#st-user-dropdown [data-action=reset-layout],#st-options-search-wrap,#st-options-body,.st-theme-profile-row{display:none !important}</style>').appendTo(document.head);
	}

	// ---- One app on the rail: hide the rail, put the brand mark beside the company name ----------------
	// The server decides (navigation.boot_session: not System Manager, not an accountant), so the class is on <html>
	// before the rail draws and there is no flash of it. The sidebar's company header is text-only by design (the theme
	// left the logo to the rail's tile), so the mark is added to it here, only while the rail is hidden.
	function isSingleApp() {
		return !!(frappe.boot && frappe.boot.retail_store_single_app);
	}
	function singleAppSetup() {
		if (!isSingleApp()) return;
		document.documentElement.classList.add("rs-single-app");
		$('<style id="rs-single-app-css">' +
			"html.rs-single-app #st-icon-rail{display:none !important}" +
			"html.rs-single-app #st-company-header{display:flex;align-items:center;gap:10px}" +
			"html.rs-single-app #st-company-header .rs-brand-mark{height:28px;width:auto;max-width:56px;object-fit:contain;flex:none}" +
			"</style>").appendTo(document.head);
		const place = () => {
			const header = document.getElementById("st-company-header");
			if (!header || header.querySelector(".rs-brand-mark")) return;
			const src = frappe.boot.retail_store_brand_mark;
			if (!src) return;
			const img = document.createElement("img");
			img.className = "rs-brand-mark";
			img.alt = "";
			img.src = src;
			header.insertBefore(img, header.firstChild);
		};
		new MutationObserver(place).observe(document.documentElement, { childList: true, subtree: true });
		place();
	}

	// ---- "All Options" now only holds Appearance for everyone but System Manager: say so ------------------
	function appearanceLabel() {
		const roles = (frappe.boot && frappe.boot.user && frappe.boot.user.roles) || [];
		if (!roles.length || roles.indexOf("System Manager") !== -1) return;
		$('<style id="rs-appearance-css">#st-op-appearance .st-op-section-head{display:none !important}</style>').appendTo(document.head);
		const word = __("Appearance");
		const relabel = () => {
			const btn = document.getElementById("st-options-btn");
			if (btn && btn.dataset.rsLabel !== "1") {
				btn.dataset.rsLabel = "1";
				btn.title = word;
				btn.setAttribute("aria-label", word);
				const label = btn.querySelector(".st-options-label");
				if (label) label.textContent = word;
			}
			const head = document.querySelector("#st-options-panel-head h3");
			if (head && head.dataset.rsLabel !== "1") {
				head.dataset.rsLabel = "1";
				head.textContent = "\u2637 " + word;
			}
		};
		new MutationObserver(relabel).observe(document.documentElement, { childList: true, subtree: true });
		relabel();
	}

	// ---- Collapsible sidebar: Frappe v16 already folds the sidebar to an icon strip (and remembers it), but its only
	// control is a round arrow that appears while the pointer is exactly on the sidebar's right edge. Keep that arrow
	// visible and add a chevron in the header, the obvious place to look. Collapsed, the header shows the logo alone
	// (single-app users only: everyone else's rail already carries it); clicking it opens the sidebar again.
	function sidebarToggleSetup() {
		const single = isSingleApp();
		$('<style id="rs-sidebar-toggle-css">' +
			".sidebar-collapse-arrow{opacity:1 !important;pointer-events:auto !important}" +
			"#st-company-header .rs-sidebar-toggle{margin-left:auto;flex:none;display:flex;align-items:center;justify-content:center;width:26px;height:26px;border:0;border-radius:8px;background:transparent;color:var(--text-muted,#6b6a65);cursor:pointer}" +
			"#st-company-header .rs-sidebar-toggle:hover{background:var(--control-bg,rgba(0,0,0,.06))}" +
			"#st-company-header .rs-sidebar-toggle svg{width:14px;height:14px}" +
			(single
				? ".body-sidebar-container:not(.expanded) #st-company-header{display:flex !important;justify-content:center;padding:14px 0 !important;cursor:pointer}" +
				  ".body-sidebar-container:not(.expanded) #st-company-header .st-company-name,.body-sidebar-container:not(.expanded) #st-company-header .rs-sidebar-toggle{display:none !important}"
				: "") +
			"</style>").appendTo(document.head);
		const place = () => {
			const header = document.getElementById("st-company-header");
			if (!header || header.dataset.rsToggle === "1") return;
			header.dataset.rsToggle = "1";
			const btn = document.createElement("button");
			btn.type = "button";
			btn.className = "rs-sidebar-toggle";
			btn.title = __("Collapse sidebar");
			btn.setAttribute("aria-label", __("Collapse sidebar"));
			btn.innerHTML = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 3.5 5 8l4.5 4.5M13 3.5 8.5 8l4.5 4.5"/></svg>';
			header.appendChild(btn);
		};
		new MutationObserver(place).observe(document.documentElement, { childList: true, subtree: true });
		place();
		const toggle = () => frappe.app && frappe.app.sidebar && frappe.app.sidebar.toggle_width();
		document.addEventListener("click", (e) => {
			if (e.target.closest && e.target.closest("#st-company-header .rs-sidebar-toggle")) return toggle();
			// collapsed + logo only: the header is the way back in
			const header = e.target.closest && e.target.closest("#st-company-header");
			if (header && single && !document.querySelector(".body-sidebar-container.expanded")) toggle();
		});
	}

	singleAppSetup();
	appearanceLabel();
	sidebarToggleSetup();

	$(document).on("startup", () => {
		apply(frappe.boot && frappe.boot.retail_store_branding);
		hideCredit();
	});
	if (window.frappe && frappe.boot && frappe.boot.retail_store_branding) {
		apply(frappe.boot.retail_store_branding);
	}
})();
