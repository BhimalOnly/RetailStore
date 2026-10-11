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

	$(document).on("startup", () => {
		apply(frappe.boot && frappe.boot.retail_store_branding);
		hideCredit();
	});
	if (window.frappe && frappe.boot && frappe.boot.retail_store_branding) {
		apply(frappe.boot.retail_store_branding);
	}
})();
