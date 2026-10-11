// Clock in / out for the shop floor. Reached from the POS menu; no Desk forms involved.
// Server side: retail_store.hr.clock_status / clock (HRMS add_log_based_on_employee_field).

frappe.pages["store-clock"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Clock In / Out"), single_column: true });
	const $body = $(`<div class="rs-clock"></div>`).appendTo(page.main);
	$(`<style>
		.rs-clock{max-width:420px;margin:32px auto;text-align:center}
		.rs-clock .rs-who{font-size:var(--text-lg);font-weight:600}
		.rs-clock .rs-store{color:var(--text-muted);margin-bottom:20px}
		.rs-clock .rs-state{font-size:var(--text-xl,1.25rem);margin:16px 0 4px}
		.rs-clock .rs-btn{width:100%;padding:22px;font-size:1.4rem;border-radius:var(--border-radius-lg,12px)}
		.rs-clock .rs-meta{color:var(--text-muted);margin:10px 0 24px}
		.rs-clock .rs-log{list-style:none;padding:0;margin:0;text-align:left}
		.rs-clock .rs-log li{display:flex;justify-content:space-between;padding:8px 4px;border-top:1px solid var(--border-color)}
		.rs-clock .rs-pos{display:block;margin-top:24px}
		/* chrome-free while on this page: shop-floor staff get this screen and the way back to POS, nothing else */
		body.rs-clock-bare #st-top-toolbar, body.rs-clock-bare #st-icon-rail,
		body.rs-clock-bare .body-sidebar-container, body.rs-clock-bare .page-head{display:none !important}
		body.rs-clock-bare .main-section, body.rs-clock-bare #body, body.rs-clock-bare .desk-body{margin-left:0 !important;padding-left:0 !important;width:100% !important;max-width:100% !important}
	</style>`).appendTo($body);
	const $card = $(`<div></div>`).appendTo($body);

	const hhmm = (t) => (t || "").slice(11, 16);

	function render(s) {
		if (!s.employee) {
			$card.html(`<p class="rs-state">${__("No employee record is linked to your login.")}</p>
				<p class="rs-meta">${__("Ask the store owner to link your user to your Employee record.")}</p>`);
			return;
		}
		const out = s.next === "OUT";
		$card.html(`
			<div class="rs-who">${frappe.utils.escape_html(s.employee_name)}</div>
			<div class="rs-store">${frappe.utils.escape_html(s.store || "")}</div>
			<div class="rs-state">${out ? __("Clocked in since {0}", [hhmm(s.clocked_in_since)]) : __("Clocked out")}</div>
			<div class="rs-meta">${__("Worked today")}: ${s.worked_hours} h</div>
			<button class="btn ${out ? "btn-default" : "btn-primary"} rs-btn">${out ? __("Clock Out") : __("Clock In")}</button>
			<ul class="rs-log mt-4">${s.logs
				.map((l) => `<li><span>${l.log_type === "IN" ? __("In") : __("Out")}</span><span>${hhmm(l.time)}</span></li>`)
				.join("")}</ul>
			<a class="rs-pos" href="/desk/point-of-sale">${__("Back to Point of Sale")}</a>`);
		$card.find(".rs-btn").on("click", function () {
			$(this).prop("disabled", true);
			frappe
				.call({ method: "retail_store.hr.clock", args: { log_type: s.next }, type: "POST" })
				.then((r) => {
					frappe.show_alert({ message: out ? __("Clocked out") : __("Clocked in"), indicator: "green" });
					render(r.message);
				})
				.catch(() => load());
		});
	}

	function load() {
		frappe.call({ method: "retail_store.hr.clock_status" }).then((r) => render(r.message));
	}
	wrapper.load = load;
	load();
};

// on_page_hide is not reliable across Desk versions, so drop the bare layout on any route change
frappe.router.on("change", () => {
	if (frappe.get_route()[0] !== "store-clock") $("body").removeClass("rs-clock-bare");
});

frappe.pages["store-clock"].on_page_show = function (wrapper) {
	$("body").addClass("rs-clock-bare");
	if (wrapper.load) wrapper.load();
};
