// Copyright (c) 2026, bhimall and contributors
// For license information, please see license.txt

frappe.ui.form.on("Retail Store Settings", {
	setup(frm) {
		// every field here is optional, so the theme's "Show optional fields" fold would hide the whole
		// page (main warehouse, extra staff permissions...). This is a settings page: show it all.
		frm.meta.st_disable_progressive = 1;
	},
	after_save() {
		// Navigation and colours are read at boot, so reload to show the result.
		frappe.show_alert({ message: __("Applied. Reloading…"), indicator: "green" });
		setTimeout(() => window.location.reload(), 800);
	},
});
