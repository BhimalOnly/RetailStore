// A required field is never left hidden by the theme's "Show N optional fields" fold.
//
// The fold (solvronix_desk progressive_forms.js) hides every field that is not required, once, ~150 ms after a
// saved form loads. But "required" can change afterwards: Employee Status = Left makes Date of Relieving
// mandatory, Attendance On Leave needs a Leave Type, a Payment Entry on a bank account needs a reference number
// and date, an Item with batches and expiry needs a shelf life. The field stayed folded away, so Save said
// "Missing Values Required" and there was nothing to fix it with (the same shape as the Customer / Country bug).
//
// This keeps the fold honest, without touching the theme:
//  * whenever Frappe re-evaluates the conditions (Layout.refresh_dependency), a field that is now required is
//    revealed, with a short note saying so (and which tab it is on, if not the open one)
//  * a failed Save reveals the missing field before Frappe scrolls to it (scroll_to_field switches the tab, but
//    scrolling to a folded field shows nothing)
//  * pressing the fold's own "Hide optional fields" never re-hides a required field
// A required field inside a collapsed section opens that section too. Optional fields stay folded exactly as before.
(function () {
	const FIELD_HIDDEN = "st-pf-hidden";
	const HEAD_HIDDEN = "st-pf-section-head-hidden";
	const LAYOUT = ["Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading"];

	function missing(field) {
		const frm = field.frm;
		const v = frm && frm.doc ? frm.doc[field.df.fieldname] : undefined;
		return v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0);
	}

	function reveal_field(field, announce) {
		const df = field && field.df;
		const el = field && field.$wrapper && field.$wrapper[0];
		if (!df || !el || LAYOUT.indexOf(df.fieldtype) !== -1) return false;
		if (!df.reqd || df.hidden || el.classList.contains("hide-control")) return false; // nothing to show right now
		let changed = false;
		if (el.classList.contains(FIELD_HIDDEN)) {
			el.classList.remove(FIELD_HIDDEN);
			const section = el.closest(".form-section");
			const head = section && section.querySelector(".section-head");
			if (head) head.classList.remove(HEAD_HIDDEN);
			changed = true;
		}
		// a required field inside a COLLAPSED section (Customize Form collapses rarely used sections) opens it
		const sec = field.section;
		if (sec && sec.is_collapsed && sec.is_collapsed()) {
			sec.collapse(false);
			changed = true;
		}
		// only say so when the person has something to do: a field that is required AND still empty. A filled one (Currency, Status on
		// every sales document) is revealed quietly; announcing it repeated "is now required" on every edit.
		if (changed && announce && missing(field) && window.frappe && frappe.show_alert) {
			const where = field.tab && !field.tab.is_active() ? " " + __("(on the {0} tab)", [field.tab.label || (field.tab.df || {}).label || ""]) : "";
			frappe.show_alert({ message: __("{0} is now required", [__(df.label || df.fieldname)]) + where, indicator: "orange" }, 6);
		}
		return changed;
	}

	// A form that is not on screen has nothing to reveal and nobody to tell. The POS keeps a Sales Invoice form of its
	// own that is never attached to the page: it is built, filled and saved in the background, and its required fields
	// (Currency, Debit To) are set by the server. Announcing them there repeated "is now required" on every item added,
	// piling up over the Checkout button.
	function on_screen(frm) {
		const el = frm && frm.$wrapper && frm.$wrapper[0];
		return !!(el && el.isConnected && el.getClientRects().length);
	}

	function reveal_required(frm, announce) {
		if (!frm || !frm.fields || !on_screen(frm)) return;
		frm.fields.forEach((f) => reveal_field(f, announce));
	}

	const pending = new WeakMap();
	function schedule(frm, announce) {
		clearTimeout(pending.get(frm));
		pending.set(frm, setTimeout(() => reveal_required(frm, announce), 0));
	}

	function patch() {
		const form = window.frappe && frappe.ui && frappe.ui.form;
		if (!form || !form.Layout || !form.Form) return false;
		if (form.Layout.prototype.__rs_guard) return true;
		form.Layout.prototype.__rs_guard = true;

		const refresh_dependency = form.Layout.prototype.refresh_dependency;
		form.Layout.prototype.refresh_dependency = function () {
			const out = refresh_dependency.apply(this, arguments);
			// the first pass runs while the form is still being built (the theme has not folded anything yet): only
			// later passes, caused by the person editing a field, can newly require one
			if (this.frm && this.frm.__rs_guard_ready) schedule(this.frm, true);
			return out;
		};

		const scroll_to_field = form.Form.prototype.scroll_to_field;
		form.Form.prototype.scroll_to_field = function (fieldname) {
			const field = this.get_field && this.get_field(fieldname);
			if (field) reveal_field(field, false);
			return scroll_to_field.apply(this, arguments);
		};

		frappe.ui.form.on("*", {
			refresh: function (frm) {
				setTimeout(function () {
					reveal_required(frm, false); // after the theme's own pass at 150 ms
					frm.__rs_guard_ready = true;
				}, 500);
			},
		});

		$(document).on("click", ".st-pf-toggle-btn", function () {
			const frm = window.cur_frm;
			setTimeout(() => reveal_required(frm, false), 0);
		});
		return true;
	}

	let tries = 0;
	const timer = setInterval(function () {
		if (patch() || ++tries > 100) clearInterval(timer);
	}, 200);
})();
