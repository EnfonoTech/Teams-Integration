// Copyright (c) 2026, siva@enfono.com

let _ti_event_settings_cache = null;

async function ti_get_settings() {
	if (!_ti_event_settings_cache) {
		_ti_event_settings_cache = await frappe.db.get_doc("Teams Settings", "Teams Settings");
	}
	return _ti_event_settings_cache;
}

frappe.ui.form.on("Event", {
	async refresh(frm) {
		const settings_doc = await ti_get_settings();
		const enabledSet = new Set(
			(settings_doc.enabled_doctypes || []).map((r) => r.doctype_name)
		);

		const buttons = [
			"Create Teams Chat", "Open Teams Chat", "Send Teams Message",
			"Post to Channel", "Create Teams Meeting", "Reschedule Teams Meeting",
			"Sync Now", "Cancel Teams Meeting",
		];

		if (!enabledSet.has(frm.doctype)) {
			buttons.forEach((b) => frm.remove_custom_button(__(b), __("Teams")));
			return;
		}

		// Wire up "Join Teams Meeting" button if URL exists
		if (frm.doc.custom_teams_meeting_url) {
			frm.fields_dict.custom_join_teams_meeting.$wrapper
				.find("button")
				.off("click")
				.on("click", function () {
					window.open(frm.doc.custom_teams_meeting_url, "_blank");
				});
		}

		// Handle auth redirect status
		const urlParams = new URLSearchParams(window.location.search);
		if (urlParams.get("teams_authentication_status") === "success") {
			frappe.show_alert({ message: __("Teams token saved after login."), indicator: "green" });
			const cleanURL = new URL(window.location.href);
			cleanURL.searchParams.delete("teams_authentication_status");
			window.history.replaceState({}, document.title, cleanURL.pathname);
		}

		if (frm.doc.__islocal) return;

		frm.add_custom_button(__("Create Teams Chat"), () => {
			frappe.call({
				method: "teams_integration.api.chat.create_group_chat_for_doc",
				args: { docname: frm.doc.name, doctype: frm.doc.doctype },
				callback: function (r) {
					if (r.message && r.message.chat_id) {
						frappe.show_alert({ message: __("Teams chat created and linked."), indicator: "green" });
						frm.reload_doc();
					} else if (r.message && r.message.login_url) {
						window.location.href = r.message.login_url;
					}
				},
			});
		}, __("Teams"));

		frm.add_custom_button(__("Open Teams Chat"), () => {
			frappe.call({
				method: "teams_integration.api.chat.get_local_chat_messages",
				args: { chat_id: frm.doc.custom_teams_chat_id },
				callback: function (r) {
					let messages = r.message || [];
					let chat_html = messages
						.map(
							(m) =>
								`<div style="padding:10px;border-bottom:1px solid var(--border-color);">
									<strong>${m.sender_display || m.sender_id}</strong>
									<span style="color:var(--text-muted);font-size:0.85em;margin-left:8px;">${m.created_at || ""}</span>
									<div style="margin-top:6px;">${m.body}</div>
								</div>`
						)
						.join("");
					if (!chat_html)
						chat_html = '<div class="text-muted p-4 text-center">No messages found.</div>';

					new frappe.ui.Dialog({
						title: __("Teams Chat History"),
						fields: [
							{
								fieldname: "chat_container",
								fieldtype: "HTML",
								options: `<div style="max-height:400px;overflow-y:auto;">${chat_html}</div>`,
							},
						],
						size: "large",
					}).show();
				},
			});
		}, __("Teams"));

		frm.add_custom_button(__("Send Teams Message"), () => {
			frappe.prompt(
				[{ fieldname: "message", fieldtype: "Small Text", label: __("Message"), reqd: 1 }],
				function (vals) {
					frappe.call({
						method: "teams_integration.api.chat.send_message_to_chat",
						args: {
							chat_id: frm.doc.custom_teams_chat_id,
							message: vals.message,
							docname: frm.doc.name,
							doctype: frm.doc.doctype,
						},
						callback: function () {
							frappe.show_alert({ message: __("Message sent to Teams"), indicator: "green" });
							frm.reload_doc();
						},
					});
				},
				__("Send Teams Message"),
				__("Send")
			);
		}, __("Teams"));

		frm.add_custom_button(__("Post to Channel"), () => {
			frappe.prompt(
				[
					{ fieldname: "team_id", fieldtype: "Data", label: __("Team ID"), reqd: 1 },
					{ fieldname: "channel_id", fieldtype: "Data", label: __("Channel ID"), reqd: 1 },
					{ fieldname: "message", fieldtype: "Small Text", label: __("Message"), reqd: 1 },
				],
				function (vals) {
					frappe.call({
						method: "teams_integration.api.chat.post_message_to_channel",
						args: {
							team_id: vals.team_id,
							channel_id: vals.channel_id,
							message: vals.message,
							docname: frm.doc.name,
						},
						callback: function () {
							frappe.show_alert({ message: __("Posted to channel"), indicator: "blue" });
						},
					});
				},
				__("Post to Channel"),
				__("Post")
			);
		}, __("Teams"));

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

		frm.add_custom_button(__("Sync Now"), () => {
			let args = {};
			if (frm.doc.custom_teams_chat_id) args.chat_id = frm.doc.custom_teams_chat_id;
			frappe.call({
				method: "teams_integration.api.chat.sync_all_conversations",
				args: args,
				callback: function (r) {
					if (!r.exc)
						frappe.show_alert({ message: __("Chats synced successfully."), indicator: "green" });
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

		// Feature 7: External Guest Invite
		frm.add_custom_button(__("Invite External Guest"), () => {
			frappe.prompt(
				[{
					fieldname: "external_emails",
					fieldtype: "Small Text",
					label: __("External Email Addresses (comma-separated)"),
					reqd: 1,
					default: frm.doc.custom_external_attendees || "",
				}],
				function (vals) {
					frappe.call({
						method: "teams_integration.api.meetings.add_external_attendees",
						args: { docname: frm.doc.name, doctype: frm.doc.doctype, external_emails: vals.external_emails },
						callback: function (r) {
							if (r.message && r.message.success) {
								frappe.show_alert({ message: r.message.message, indicator: "green" });
								frm.reload_doc();
							}
						},
					});
				},
				__("Invite External Guest"),
				__("Invite")
			);
		}, __("Teams"));

		// Feature 2: Adaptive Cards
		if (frm.doc.custom_teams_chat_id) {
			frm.add_custom_button(__("Send Approval Card"), () => {
				frappe.prompt(
					[{ fieldname: "note", fieldtype: "Small Text", label: __("Note (optional)") }],
					function (vals) {
						frappe.call({
							method: "teams_integration.api.adaptive_cards.send_approval_card",
							args: { chat_id: frm.doc.custom_teams_chat_id, doctype: frm.doc.doctype, docname: frm.doc.name, note: vals.note },
							callback: function (r) {
								if (r.message && r.message.success)
									frappe.show_alert({ message: __("Approval card sent to Teams"), indicator: "green" });
							},
						});
					},
					__("Send Approval Card"),
					__("Send")
				);
			}, __("Teams"));

			if (frm.doc.custom_teams_meeting_url) {
				frm.add_custom_button(__("Share Meeting Card"), () => {
					frappe.call({
						method: "teams_integration.api.adaptive_cards.send_meeting_invite_card",
						args: {
							chat_id: frm.doc.custom_teams_chat_id,
							doctype: frm.doc.doctype,
							docname: frm.doc.name,
							meeting_url: frm.doc.custom_teams_meeting_url,
							start_time: frm.doc.starts_on,
							end_time: frm.doc.ends_on,
						},
						callback: function (r) {
							if (r.message && r.message.success)
								frappe.show_alert({ message: __("Meeting card shared in Teams"), indicator: "green" });
						},
					});
				}, __("Teams"));
			}
		}

		// Feature 5: Recordings & Transcripts
		if (frm.doc.custom_teams_meeting_url) {
			frm.add_custom_button(__("Fetch Recording"), () => {
				frappe.show_alert({ message: __("Fetching recording…"), indicator: "blue" });
				frappe.call({
					method: "teams_integration.api.meetings.fetch_meeting_recordings",
					args: { docname: frm.doc.name, doctype: frm.doc.doctype },
					callback: function (r) {
						if (!r.message) return;
						if (r.message.error === "auth_required") {
							frappe.set_route("Form", "Teams Settings", "Teams Settings");
							return;
						}
						const recs = r.message.recordings || [];
						if (!recs.length) {
							frappe.show_alert({ message: r.message.message || __("No recordings found yet."), indicator: "orange" });
							return;
						}
						frm.reload_doc();
						frappe.show_alert({ message: `${recs.length} recording(s) found. URL saved to record.`, indicator: "green" });
					},
				});
			}, __("Teams"));

			frm.add_custom_button(__("Fetch Transcript"), () => {
				frappe.show_alert({ message: __("Fetching transcript…"), indicator: "blue" });
				frappe.call({
					method: "teams_integration.api.meetings.fetch_meeting_transcript",
					args: { docname: frm.doc.name, doctype: frm.doc.doctype },
					callback: function (r) {
						if (!r.message) return;
						const trs = r.message.transcripts || [];
						if (!trs.length) {
							frappe.show_alert({ message: r.message.message || __("No transcripts found yet."), indicator: "orange" });
							return;
						}
						frm.reload_doc();
						frappe.show_alert({ message: `${trs.length} transcript(s) found. URL saved to record.`, indicator: "green" });
					},
				});
			}, __("Teams"));
		}
	},
});
