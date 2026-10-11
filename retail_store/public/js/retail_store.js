// Applies per-site brand colours from Retail Store Settings as CSS variables.
// Deliberately tiny: no stylesheet, no DOM rewrites, so a Desk theme app can coexist.
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
		$('<style id="rs-no-credit">#st-powered-by{display:none !important}</style>').appendTo(document.head);
	}

	$(document).on("startup", () => {
		apply(frappe.boot && frappe.boot.retail_store_branding);
		hideCredit();
	});
	if (window.frappe && frappe.boot && frappe.boot.retail_store_branding) {
		apply(frappe.boot.retail_store_branding);
	}
})();
