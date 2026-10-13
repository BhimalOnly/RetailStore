// Dialogs: the one on top owns the keyboard.
//
// A message ("Missing Values Required") opens over the dialog it is about, but keyboard focus stayed in the dialog
// underneath, so Escape closed THAT one (taking what the person had typed with it) and left the message. Now:
//  * every open dialog is tagged with its depth (data-rs-depth 1, 2, ...) from Frappe's own stack, which dialogs.css
//    uses to sit a stacked message clear of the header below it (the DOM order is not the opening order: Frappe
//    re-uses one message element)
//  * focus moves to the dialog on top when it opens
//  * Escape closes only the dialog on top; a blocking one (static: no close button, e.g. "An earlier shift is still
//    open") ignores Escape as before, without letting the dialogs under it close either
(function () {
	function stack() {
		const open = (window.frappe && frappe.ui && frappe.ui.open_dialogs) || [];
		return open.filter((d) => d.$wrapper && d.$wrapper[0] && d.$wrapper.hasClass("show"));
	}

	function tag_depths() {
		stack().forEach((d, i) => d.$wrapper.attr("data-rs-depth", i + 1));
	}

	function focus_top() {
		const top = stack().pop();
		if (!top) return;
		const el = top.$wrapper[0];
		if (!el.contains(document.activeElement)) {
			el.setAttribute("tabindex", "-1");
			el.focus({ preventScroll: true });
		}
	}

	if (window.jQuery) {
		jQuery(document).on("shown.bs.modal hidden.bs.modal", ".modal", function () {
			setTimeout(function () {
				tag_depths();
				focus_top();
			}, 30); // after Frappe has pushed / popped its own stack
		});
	}

	document.addEventListener(
		"keydown",
		function (e) {
			if (e.key !== "Escape") return;
			const open = stack();
			if (open.length < 2) return; // one dialog: Frappe's own handling is fine
			const top = open[open.length - 1];
			e.preventDefault();
			e.stopImmediatePropagation();
			const bs = window.jQuery && jQuery(top.$wrapper[0]).data("bs.modal");
			if (top.static || (bs && bs._config && bs._config.keyboard === false)) return; // blocking dialog
			top.hide();
		},
		true
	);
})();
