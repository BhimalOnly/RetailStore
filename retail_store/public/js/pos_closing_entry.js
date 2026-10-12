// POS Closing Entry, the end-of-shift form every cashier meets daily. ERPNext's form is a wall of read-only
// fields (period, posting date/time, company, profile, totals...). For shop-floor staff this keeps the form and
// ERPNext's own closing validation, and only declutters it: the facts collapse into one summary line, the
// payment table (expected / counted / difference) is the focus, and the button says Close shift. Owners,
// managers, admins and accountants keep the full form.
// Where the cashier lands afterwards depends on why they closed (set by pos_variant_picker.js):
//   "end"   -> Retail Store home (end of day: nothing left to do in POS)
//   "stale" -> back into POS to open today's shift (closing the old one was only in the way of selling)

(function () {
	const FULL = ["Store Owner", "Store Admin", "Store Manager", "System Manager", "Accounts Manager", "Accounts User"];
	const full_form = () => FULL.some((r) => frappe.user.has_role(r));
	const HIDE = [
		"period_details_section",
		"section_break_5",
		"section_break_13",
		"section_break_12",
		"section_break_14",
		"taxes_and_charges_section",
	];
	const LABELS = { opening_amount: __("Opening cash"), expected_amount: __("Expected"), closing_amount: __("Counted"), difference: __("Difference") };

	function read_reason() {
		try {
			return sessionStorage.getItem("rs_close_reason");
		} catch (e) {
			return null;
		}
	}
	function clear_reason() {
		try {
			sessionStorage.removeItem("rs_close_reason");
		} catch (e) {}
	}

	// frappe.user_info(self).fullname is "You"; the summary should name the cashier
	function who(user) {
		const name = user === frappe.session.user ? frappe.session.user_fullname : (frappe.user_info(user) || {}).fullname;
		return (name || user).replace(/^DEMO /, "");
	}

	function summary(frm) {
		const d = frm.doc;
		const parts = [];
		if (d.pos_profile) parts.push(frappe.utils.escape_html(d.pos_profile.replace(/^DEMO /, "")));
		if (d.user) parts.push(frappe.utils.escape_html(who(d.user)));
		if (d.period_start_date) parts.push(__("opened {0}", [frappe.datetime.str_to_user(d.period_start_date)]));
		const sales = (d.pos_invoices || []).length + (d.sales_invoices || []).length;
		if (sales) parts.push(__("{0} sales", [sales]) + " &middot; " + format_currency(d.grand_total, frappe.defaults.get_default("currency")));
		return parts.join(" &middot; ");
	}

	// the summary line and the instruction share Frappe's one form message, so they are set together
	function paint(frm) {
		const text = summary(frm);
		const hint = frm.doc.docstatus === 0
			? `<div>${__("Count what is in the drawer for each payment method and type it under Counted. Then press Close shift.")}</div>`
			: "";
		const html = (text ? `<div class="rs-close-summary"><b>${text}</b></div>` : "") + hint;
		if (html && frm.layout && (!frm.layout.message || frm.layout.message.html().indexOf("rs-close-summary") === -1 || frm.__rs_last !== html)) {
			frm.__rs_last = html;
			frm.set_intro(html, "blue");
		}
	}

	function difference_formatter(value) {
		const v = flt(value);
		const colour = v === 0 ? "var(--green-600, #2e8b6f)" : v < 0 ? "var(--red-600, #c0392b)" : "var(--orange-600, #d9822b)";
		const word = v === 0 ? __("OK") : v < 0 ? __("Short") : __("Over");
		return `<span style="color:${colour};font-weight:600">${format_currency(v, frappe.defaults.get_default("currency"))} <small>${word}</small></span>`;
	}

	// after submitting, wait for ERPNext's background closing job, then leave
	function leave_when_closed(frm, target) {
		frappe.dom.freeze(__("Closing your shift..."));
		let tries = 0;
		const check = () => {
			frappe.db.get_value("POS Closing Entry", frm.doc.name, "status").then(({ message }) => {
				const status = message && message.status;
				if (status === "Failed") {
					frappe.dom.unfreeze();
					return; // ERPNext shows its own failure message on the form
				}
				if (status === "Submitted" || ++tries > 40) {
					frappe.dom.unfreeze();
					frappe.show_alert({ message: __("Shift closed"), indicator: "green" });
					frappe.set_route(target);
					return;
				}
				setTimeout(check, 1000);
			});
		};
		check();
	}

	frappe.ui.form.on("POS Closing Entry", {
		refresh(frm) {
			if (full_form()) return;
			HIDE.forEach((f) => frm.set_df_property(f, "hidden", 1));
			const grid = frm.fields_dict.payment_reconciliation && frm.fields_dict.payment_reconciliation.grid;
			if (grid) {
				Object.entries(LABELS).forEach(([field, label]) => grid.update_docfield_property(field, "label", label));
				const df = (grid.docfields || []).find((f) => f.fieldname === "difference");
				if (df) df.formatter = difference_formatter;
			}
			paint(frm);
			// Frappe sets its own Save/Submit button and clears messages at moments of its own choosing, and the
			// totals arrive a moment after the form opens: keep our summary, instruction and button in place while
			// the form settles
			const settle = () => {
				paint(frm);
				if (frm.doc.docstatus !== 0) return;
				const label = __("Close shift");
				if (!frm.page.btn_primary || frm.page.btn_primary.text().trim() !== label) {
					frm.page.set_primary_action(label, () => {
						frappe.confirm(__("Close this shift? You will not be able to change the counts afterwards."), () => frm.save("Submit"));
					});
				}
			};
			settle();
			let n = 0;
			const timer = setInterval(() => {
				if (cur_frm !== frm || ++n > 20) return clearInterval(timer);
				settle();
			}, 600);
		},

		// (on_submit does not fire for this form; after_save does, for the submit as well)
		after_save(frm) {
			if (frm.doc.docstatus !== 1) return;
			const reason = read_reason();
			if (!reason) return;
			clear_reason();
			leave_when_closed(frm, reason === "stale" ? "point-of-sale" : "retail-store");
		},
	});
})();
