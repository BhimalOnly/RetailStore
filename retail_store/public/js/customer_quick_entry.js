// POS / Desk "New Customer" quick entry (ERPNext's ContactAddressQuickEntryForm), made safe for a till.
//
// 1. The opt-in boxes (Offers by WhatsApp / SMS) are forced OFF every time the dialog opens, with a plain line
//    under them: consent is only ever the customer's own yes (retail_store/messaging/consent.py).
// 2. A retail customer is an Individual, not a Company (ERPNext's default, which also hides first/last name),
//    and Country starts as the company's country (Mauritius): it becomes mandatory the moment an address line
//    or city is typed, and the full Customer form has no Country field to fix it in.
// 3. "Edit Full Form" hands over the REAL field names. The dialog works with aliases (country_address,
//    email_address, mobile_number, map_to_first_name...) and ERPNext maps them to country / email_id /
//    mobile_no / first_name only when you press Save. Edit Full Form skipped that, so the full form had no
//    Country, no way to type one, and refused to save ("Missing Values Required: Country").
(function () {
	const ALIASES = {
		email_address: "email_id",
		mobile_number: "mobile_no",
		map_to_first_name: "first_name",
		map_to_last_name: "last_name",
		country_address: "country",
	};
	const CONSENT = ["custom_whatsapp_optin", "custom_sms_optin"];

	function customer_defaults(qe) {
		CONSENT.forEach((f) => qe.set_value(f, 0));
		qe.set_value("customer_type", "Individual");
		const sms = qe.fields_dict && qe.fields_dict.custom_sms_optin;
		if (sms && !qe.$rs_hint) {
			qe.$rs_hint = $('<div class="rs-consent-hint text-muted small"></div>').text(__("Only tick if the customer said yes."));
			$(sms.wrapper).after(qe.$rs_hint);
		}
		const company = frappe.defaults.get_user_default("Company") || (frappe.boot.sysdefaults || {}).company;
		if (company) {
			frappe.db.get_value("Company", company, "country").then((r) => {
				const country = r && r.message && r.message.country;
				if (country && !qe.get_value("country_address")) qe.set_value("country_address", country);
			});
		}
	}

	function patch() {
		const QE = frappe.ui && frappe.ui.form && frappe.ui.form.ContactAddressQuickEntryForm;
		if (!QE) return false;
		if (QE.prototype.__rs_patched) return true;
		QE.prototype.__rs_patched = true;

		const render_dialog = QE.prototype.render_dialog;
		QE.prototype.render_dialog = function () {
			render_dialog.call(this);
			if (this.doctype === "Customer") customer_defaults(this);
		};

		const open_doc = QE.prototype.open_doc;
		QE.prototype.open_doc = function (set_hooks) {
			this.update_doc();
			[this.doc, this.dialog && this.dialog.doc].forEach((doc) => {
				if (!doc) return;
				Object.entries(ALIASES).forEach(([alias, real]) => {
					if (doc[alias] != null && doc[alias] !== "") doc[real] = doc[alias];
					delete doc[alias];
				});
			});
			return open_doc.call(this, set_hooks);
		};
		return true;
	}

	// the class is defined by ERPNext's bundle; this file may load first, so wait for it
	let tries = 0;
	const timer = setInterval(function () {
		if (patch() || ++tries > 100) clearInterval(timer);
	}, 200);
})();
