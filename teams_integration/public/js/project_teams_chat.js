// Copyright (c) 2026, siva@enfono.com

let _ti_project_settings_cache = null;

async function ti_project_get_settings() {
	if (!_ti_project_settings_cache) {
		_ti_project_settings_cache = await frappe.db.get_doc("Teams Settings", "Teams Settings");
	}
	return _ti_project_settings_cache;
}

frappe.ui.form.on("Project", {
	async refresh(frm) {
		const settings_doc = await ti_project_get_settings();
		const enabledSet = new Set(
			(settings_doc.enabled_doctypes || []).map((r) => r.doctype_name)
		);

		const buttons = [
			"Create Teams Chat", "Open Teams Chat", "Send Teams Message", "Post to Channel",
			"Create Teams Meeting", "Reschedule Teams Meeting", "Sync Now", "Cancel Teams Meeting",
		];

		if (!enabledSet.has(frm.doctype)) {
			buttons.forEach((b) => frm.remove_custom_button(__(b), __("Teams")));
			return;
		}

		if (frm.doc.custom_teams_meeting_url) {
			frm.fields_dict.custom_join_teams_meeting.$wrapper
				.find("button")
				.off("click")
				.on("click", () => window.open(frm.doc.custom_teams_meeting_url, "_blank"));
		}

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
				callback: (r) => {
					if (r.message?.chat_id) {
						frappe.show_alert({ message: __("Teams chat created and linked."), indicator: "green" });
						frm.reload_doc();
					} else if (r.message?.login_url) {
						window.location.href = r.message.login_url;
					}
				},
			});
		}, __("Teams"));

		frm.add_custom_button(__("Open Teams Chat"), () => {
			frappe.call({
				method: "teams_integration.api.chat.get_local_chat_messages",
				args: { chat_id: frm.doc.custom_teams_chat_id },
				callback: (r) => {
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
				(vals) => {
					frappe.call({
						method: "teams_integration.api.chat.send_message_to_chat",
						args: {
							chat_id: frm.doc.custom_teams_chat_id,
							message: vals.message,
							docname: frm.doc.name,
							doctype: frm.doc.doctype,
						},
						callback: () => {
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
				(vals) => {
					frappe.call({
						method: "teams_integration.api.chat.post_message_to_channel",
						args: { team_id: vals.team_id, channel_id: vals.channel_id, message: vals.message },
						callback: () =>
							frappe.show_alert({ message: __("Posted to channel"), indicator: "blue" }),
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
				callback: (r) => {
					if (r.message) {
						let msg = typeof r.message === "string" ? r.message : r.message.message;
						if (msg) frappe.msgprint(msg);
					}
					if (r.message?.login_url) { window.location.href = r.message.login_url; return; }
					frm.reload_doc();
				},
			});
		}, __("Teams"));

		frm.add_custom_button(__("Reschedule Teams Meeting"), () => {
			frappe.call({
				method: "teams_integration.api.meetings.reschedule_meeting",
				args: { docname: frm.doc.name, doctype: frm.doc.doctype },
				callback: (r) => {
					if (r.message) {
						let msg = typeof r.message === "string" ? r.message : r.message.message;
						if (msg) frappe.msgprint(msg);
					}
					frm.reload_doc();
				},
			});
		}, __("Teams"));

		frm.add_custom_button(__("Sync Now"), () => {
			frappe.call({
				method: "teams_integration.api.chat.sync_all_conversations",
				args: frm.doc.custom_teams_chat_id ? { chat_id: frm.doc.custom_teams_chat_id } : {},
				callback: (r) => {
					if (!r.exc)
						frappe.show_alert({ message: __("Chats synced successfully."), indicator: "green" });
				},
			});
		}, __("Teams"));

		frm.add_custom_button(__("Cancel Teams Meeting"), () => {
			frappe.call({
				method: "teams_integration.api.meetings.delete_meeting",
				args: { docname: frm.doc.name, doctype: frm.doc.doctype },
				callback: (r) => {
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
				(vals) => {
					frappe.call({
						method: "teams_integration.api.meetings.add_external_attendees",
						args: { docname: frm.doc.name, doctype: frm.doc.doctype, external_emails: vals.external_emails },
						callback: (r) => {
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
					(vals) => {
						frappe.call({
							method: "teams_integration.api.adaptive_cards.send_approval_card",
							args: { chat_id: frm.doc.custom_teams_chat_id, doctype: frm.doc.doctype, docname: frm.doc.name, note: vals.note },
							callback: (r) => {
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
						},
						callback: (r) => {
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
					callback: (r) => {
						const recs = r.message && r.message.recordings || [];
						if (!recs.length) {
							frappe.show_alert({ message: (r.message && r.message.message) || __("No recordings found."), indicator: "orange" });
							return;
						}
						frm.reload_doc();
						frappe.show_alert({ message: `${recs.length} recording(s) found.`, indicator: "green" });
					},
				});
			}, __("Teams"));

			frm.add_custom_button(__("Fetch Transcript"), () => {
				frappe.show_alert({ message: __("Fetching transcript…"), indicator: "blue" });
				frappe.call({
					method: "teams_integration.api.meetings.fetch_meeting_transcript",
					args: { docname: frm.doc.name, doctype: frm.doc.doctype },
					callback: (r) => {
						const trs = r.message && r.message.transcripts || [];
						if (!trs.length) {
							frappe.show_alert({ message: (r.message && r.message.message) || __("No transcripts found."), indicator: "orange" });
							return;
						}
						frm.reload_doc();
						frappe.show_alert({ message: `${trs.length} transcript(s) found.`, indicator: "green" });
					},
				});
			}, __("Teams"));
		}
	},
});
