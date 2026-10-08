// Copyright (c) 2026, bhimall and contributors
// For license information, please see license.txt

frappe.ui.form.on("Retail Staff Access", {
	refresh(frm) {
		if (!frm.doc.user || frm.is_new()) return;
		frappe.db.get_doc("User", frm.doc.user).then((user) => {
			const roles = (user.roles || []).map((r) => r.role).sort();
			const html = roles.length
				? roles.map((r) => `<span class="indicator-pill gray" style="margin:2px">${frappe.utils.escape_html(r)}</span>`).join("")
				: `<p class="text-muted">${__("No roles")}</p>`;
			frm.get_field("roles_html").$wrapper.html(html);
		});
		frm.add_custom_button(__("Edit Roles"), () => frappe.set_route("Form", "User", frm.doc.user));
	},
});
