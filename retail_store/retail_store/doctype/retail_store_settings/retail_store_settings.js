// Copyright (c) 2026, bhimall and contributors
// For license information, please see license.txt

frappe.ui.form.on("Retail Store Settings", {
	after_save() {
		// Navigation and colours are read at boot, so reload to show the result.
		frappe.show_alert({ message: __("Applied. Reloading…"), indicator: "green" });
		setTimeout(() => window.location.reload(), 800);
	},
});
