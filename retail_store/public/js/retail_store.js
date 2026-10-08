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

	$(document).on("startup", () => apply(frappe.boot && frappe.boot.retail_store_branding));
	if (window.frappe && frappe.boot && frappe.boot.retail_store_branding) {
		apply(frappe.boot.retail_store_branding);
	}
})();
