// Copyright (c) 2026, siva@enfono.com
// Teams Integration - Employee Form actions

let _ti_employee_settings_cache = null;

async function ti_employee_get_settings() {
	if (!_ti_employee_settings_cache) {
		_ti_employee_settings_cache = await frappe.db.get_doc("Teams Settings", "Teams Settings");
	}
	return _ti_employee_settings_cache;
}

frappe.ui.form.on("Employee", {
	async refresh(frm) {
		if (frm.doc.__islocal) return;

		// --- Self-service: shown only on the current user's own Employee record ---
		const authStatus = await frappe.call({
			method: "teams_integration.api.employee_auth.get_my_auth_status",
		});
		const myAuthInfo = authStatus.message || {};
		const isMyRecord = myAuthInfo.employee_name === frm.doc.name;

		if (isMyRecord) {
			if (myAuthInfo.authenticated) {
				frm.dashboard.add_indicator(__("Teams: Personally Connected"), "green");

				frm.add_custom_button(__("Send Message To..."), () => {
					frappe.prompt(
						[
							{
								label: __("Recipient Employee"),
								fieldname: "to_employee",
								fieldtype: "Link",
								options: "Employee",
								reqd: 1,
								filters: [["name", "!=", frm.doc.name]],
							},
							{
								label: __("Message"),
								fieldname: "message",
								fieldtype: "Small Text",
								reqd: 1,
							},
						],
						function (values) {
							if (!values.message || !values.message.trim()) return;
							const recipEmail =
								frappe.db
									.get_value("Employee", values.to_employee, [
										"company_email",
										"personal_email",
									])
									.then((r) => {
										const email =
											(r.message || {}).company_email ||
											(r.message || {}).personal_email;
										if (!email) {
											frappe.msgprint(
												__("Recipient has no email. Sync their Azure ID first.")
											);
											return;
										}
										frappe.show_alert({ message: __("Sending…"), indicator: "blue" });
										frappe.call({
											method: "teams_integration.api.chat.send_employee_direct_message",
											args: { to_email: email, message: values.message.trim() },
											callback(r2) {
												if (!r2.message) return;
												if (r2.message.success) {
													frappe.show_alert({
														message: __("Message sent via your Teams account!"),
														indicator: "green",
													});
												} else if (r2.message.error === "employee_auth_required") {
													frappe.msgprint(
														__("Your personal Teams session expired. Reconnect below.")
													);
												}
											},
										});
									});
						},
						__("Send Direct Teams Message"),
						__("Send")
					);
				}, __("My Teams"));

				frm.add_custom_button(__("Disconnect My Teams"), () => {
					frappe.confirm(
						__("Remove your personal Teams connection from this Employee record?"),
						() => {
							frappe.call({
								method: "teams_integration.api.employee_auth.disconnect_my_teams",
								callback() {
									frm.reload_doc();
									frappe.show_alert({
										message: __("Personal Teams connection removed."),
										indicator: "orange",
									});
								},
							});
						}
					);
				}, __("My Teams"));
			} else {
				frm.dashboard.add_indicator(__("Teams: Not Connected (Personal)"), "orange");

				frm.add_custom_button(__("Connect My Teams Account"), () => {
					frappe.call({
						method: "teams_integration.api.employee_auth.get_employee_login_url",
						callback(r) {
							if (r.message && r.message.login_url) {
								window.location.href = r.message.login_url;
							}
						},
					});
				}, __("My Teams"));
			}
		}

		// Handle post-OAuth redirect feedback
		const urlParams = new URLSearchParams(window.location.search);
		if (urlParams.get("teams_employee_auth") === "success") {
			frappe.show_alert({ message: __("Teams personal account connected!"), indicator: "green" });
			window.history.replaceState({}, "", window.location.pathname);
		} else if (urlParams.get("teams_employee_auth") === "error") {
			frappe.show_alert({ message: __("Teams connection failed. Please try again."), indicator: "red" });
			window.history.replaceState({}, "", window.location.pathname);
		}

		// --- Sync Azure ID button ---
		frm.add_custom_button(__("Sync Teams Azure ID"), () => {
			const email = frm.doc.company_email || frm.doc.personal_email;
			if (!email) {
				frappe.msgprint({
					title: __("No Email"),
					message: __("Please set Company Email or Personal Email first."),
					indicator: "orange",
				});
				return;
			}

			frappe.show_alert({ message: __("Fetching Azure ID..."), indicator: "blue" });

			frappe.call({
				method: "teams_integration.api.helpers.get_azure_user_id_by_email",
				args: { email: email },
				callback: function (r) {
					if (r.message) {
						frappe.db.set_value("Employee", frm.doc.name, "azure_object_id", r.message)
							.then(() => {
								frm.reload_doc();
								frappe.show_alert({
									message: __("Azure ID synced: ") + r.message,
									indicator: "green",
								});
							});
					} else {
						frappe.show_alert({
							message: __(
								"Could not find Azure ID for this email. Ensure the employee exists in Microsoft Entra ID."
							),
							indicator: "red",
						});
					}
				},
			});
		}, __("Teams"));

		// --- Clear Azure ID button ---
		frm.add_custom_button(__("Clear Teams Azure ID"), () => {
			frappe.confirm(
				__("Clear the stored Azure Object ID for this employee?"),
				function () {
					frappe.db.set_value("Employee", frm.doc.name, "azure_object_id", "")
						.then(() => {
							frm.reload_doc();
							frappe.show_alert({
								message: __("Azure ID cleared."),
								indicator: "orange",
							});
						});
				}
			);
		}, __("Teams"));

		// --- Direct Chat buttons ---
		const recipientEmail = frm.doc.company_email || frm.doc.personal_email;
		if (recipientEmail) {
			frm.add_custom_button(__("Start Direct Chat"), () => {
				frappe.show_alert({ message: __("Connecting to Teams..."), indicator: "blue" });
				frappe.call({
					method: "teams_integration.api.chat.create_direct_chat",
					args: { to_email: recipientEmail },
					callback: function (r) {
						if (!r.message) return;
						if (r.message.error === "auth_required") {
							frappe.confirm(
								__("Teams authentication required. Go to Teams Settings to authenticate?"),
								() => frappe.set_route("Form", "Teams Settings", "Teams Settings")
							);
							return;
						}
						frappe.show_alert({
							message: __("Direct chat ready with ") + (frm.doc.employee_name || recipientEmail),
							indicator: "green",
						});
					},
				});
			}, __("Teams"));

			frm.add_custom_button(__("Send Direct Message"), () => {
				frappe.prompt(
					[
						{
							label: __("Message"),
							fieldname: "message",
							fieldtype: "Small Text",
							reqd: 1,
						},
					],
					function (values) {
						if (!values.message || !values.message.trim()) return;
						frappe.show_alert({ message: __("Sending..."), indicator: "blue" });
						frappe.call({
							method: "teams_integration.api.chat.send_direct_message",
							args: { to_email: recipientEmail, message: values.message.trim() },
							callback: function (r) {
								if (!r.message) return;
								if (r.message.error === "auth_required") {
									frappe.confirm(
										__("Teams authentication required. Go to Teams Settings?"),
										() => frappe.set_route("Form", "Teams Settings", "Teams Settings")
									);
									return;
								}
								if (r.message.success) {
									frappe.show_alert({
										message: __("Message sent to ") + (frm.doc.employee_name || recipientEmail),
										indicator: "green",
									});
								}
							},
						});
					},
					__("Send Direct Message to ") + (frm.doc.employee_name || frm.doc.name),
					__("Send")
				);
			}, __("Teams"));

			frm.add_custom_button(__("Open Direct Chat"), () => {
				frappe.show_alert({ message: __("Loading chat history..."), indicator: "blue" });
				frappe.call({
					method: "teams_integration.api.chat.get_direct_chat_messages",
					args: { to_email: recipientEmail, limit: 50 },
					callback: function (r) {
						if (!r.message) return;
						if (r.message.error === "auth_required") {
							frappe.confirm(
								__("Teams authentication required. Go to Teams Settings?"),
								() => frappe.set_route("Form", "Teams Settings", "Teams Settings")
							);
							return;
						}
						const messages = Array.isArray(r.message) ? r.message : [];
						let msgHtml = `<div style="max-height:420px;overflow-y:auto;padding:4px;">`;
						if (!messages.length) {
							msgHtml += `<p style="color:#888;">No messages yet in this chat.</p>`;
						} else {
							messages.forEach(function (msg) {
								const isOut = msg.direction === "Outbound";
								msgHtml += `
									<div style="margin-bottom:10px;${isOut ? "text-align:right;" : ""}">
										<span style="font-weight:600;font-size:12px;">${frappe.utils.escape_html(msg.sender_display)}</span>
										<span style="color:#aaa;font-size:11px;margin-left:6px;">${msg.created_at || ""}</span>
										<div style="margin-top:2px;padding:6px 10px;border-radius:8px;display:inline-block;
											max-width:80%;background:${isOut ? "#d1e8ff" : "#f1f1f1"};text-align:left;">
											${msg.body || ""}
										</div>
									</div>`;
							});
						}
						msgHtml += `</div>`;
						frappe.msgprint({
							title: __("Direct Chat — ") + (frm.doc.employee_name || recipientEmail),
							message: msgHtml,
							wide: true,
						});
					},
				});
			}, __("Teams"));
		}

		// Azure ID sync status
		if (frm.doc.azure_object_id) {
			frm.dashboard.add_indicator(__("Teams Linked"), "green");
		} else {
			frm.dashboard.add_indicator(__("Teams Not Linked"), "orange");
		}

		// Feature 3: Teams Presence Status
		if (frm.doc.azure_object_id) {
			frappe.call({
				method: "teams_integration.api.presence.get_employee_presence",
				args: { employee_name: frm.doc.name },
				callback: function (r) {
					if (!r.message) return;
					const { label, colour } = r.message;
					if (label && colour) {
						frm.dashboard.add_indicator(`Teams: ${label}`, colour);
					}
				},
			});
		}
	},
});
