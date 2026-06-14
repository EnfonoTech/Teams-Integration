// Copyright (c) 2026, siva@enfono.com

let _ti_interview_settings_cache = null;

async function ti_interview_get_settings() {
	if (!_ti_interview_settings_cache) {
		_ti_interview_settings_cache = await frappe.db.get_doc("Teams Settings", "Teams Settings");
	}
	return _ti_interview_settings_cache;
}

frappe.ui.form.on("Interview", {
	async refresh(frm) {
		const settings_doc = await ti_interview_get_settings();
		const enabledSet = new Set(
			(settings_doc.enabled_doctypes || []).map((r) => r.doctype_name)
		);

		const buttons = ["Create Teams Meeting", "Reschedule Teams Meeting", "Cancel Teams Meeting"];

		if (!enabledSet.has(frm.doctype)) {
			buttons.forEach((b) => frm.remove_custom_button(__(b), __("Teams")));
			return;
		}

		if (frm.doc.custom_teams_meeting_url) {
			frm.fields_dict.custom_join_teams_meeting.$wrapper
				.find("button")
				.off("click")
				.on("click", function () {
					window.open(frm.doc.custom_teams_meeting_url, "_blank");
				});
		}

		const urlParams = new URLSearchParams(window.location.search);
		if (urlParams.get("teams_authentication_status") === "success") {
			frappe.show_alert({ message: __("Teams token saved after login."), indicator: "green" });
			const cleanURL = new URL(window.location.href);
			cleanURL.searchParams.delete("teams_authentication_status");
			window.history.replaceState({}, document.title, cleanURL.pathname);
		}

		if (frm.doc.__islocal) return;

		frm.add_custom_button(__("Create Teams Meeting"), () => {
			frappe.call({
				method: "teams_integration.api.meetings.create_meeting",
				args: { docname: frm.doc.name, doctype: frm.doc.doctype },
				callback: function (r) {
					if (r.message) {
						let msg = typeof r.message === "string" ? r.message : r.message.message;
						if (msg) frappe.msgprint(msg);
					}
					if (r.message && r.message.login_url) {
						window.location.href = r.message.login_url;
						return;
					}
					frm.reload_doc();
				},
			});
		}, __("Teams"));

		frm.add_custom_button(__("Reschedule Teams Meeting"), () => {
			frappe.call({
				method: "teams_integration.api.meetings.reschedule_meeting",
				args: { docname: frm.doc.name, doctype: frm.doc.doctype },
				callback: function (r) {
					if (r.message) {
						let msg = typeof r.message === "string" ? r.message : r.message.message;
						if (msg) frappe.msgprint(msg);
					}
					frm.reload_doc();
				},
			});
		}, __("Teams"));

		frm.add_custom_button(__("Cancel Teams Meeting"), () => {
			frappe.call({
				method: "teams_integration.api.meetings.delete_meeting",
				args: { docname: frm.doc.name, doctype: frm.doc.doctype },
				callback: function (r) {
					if (r.message) {
						let msg = typeof r.message === "string" ? r.message : r.message.message;
						if (msg) frappe.msgprint(msg);
					}
					frm.reload_doc();
				},
			});
		}, __("Teams"));
	},
});
