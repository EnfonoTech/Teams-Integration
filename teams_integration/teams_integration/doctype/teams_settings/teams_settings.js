// Copyright (c) 2026, siva@enfono.com

frappe.ui.form.on("Teams Settings", {
	refresh: function (frm) {
		if (!frm.is_new()) {
			// Authentication status indicator
			if (frm.doc.access_token) {
				frm.dashboard.add_indicator(__("Authenticated"), "green");
				if (frm.doc.token_expiry) {
					const expiry = new Date(frm.doc.token_expiry);
					const now = new Date();
					const hoursUntilExpiry = (expiry - now) / (1000 * 60 * 60);
					if (hoursUntilExpiry <= 0) {
						frm.dashboard.add_indicator(__("Token Expired"), "red");
					} else if (hoursUntilExpiry < 1) {
						frm.dashboard.add_indicator(__("Token Expires Soon"), "yellow");
					}
				}
			} else {
				frm.dashboard.add_indicator(__("Not Authenticated"), "red");
			}

			// --- Primary Action ---
			frm.add_custom_button(__("Authenticate with Teams"), function () {
				frappe.call({
					method: "teams_integration.api.helpers.get_login_url",
					args: { docname: frm.doc.name },
					callback: function (r) {
						if (r.message) {
							window.location.href = r.message;
						}
					},
				});
			}).addClass("btn-primary");

			// --- More Actions ---
			frm.add_custom_button(
				__("Test Connection"),
				function () {
					frappe.show_alert({ message: __("Testing connection..."), indicator: "blue" });
					frappe.call({
						method: "teams_integration.api.settings.test_teams_connection",
						callback: function (r) {
							if (r.message && r.message.success) {
								const u = r.message.user_info;
								const p = r.message.permissions;
								let msg = `Connected as: <b>${u.name}</b> (${u.email})<br><br><b>Permissions:</b><br>`;
								msg += `• Chat Access: ${p.chats ? "✅" : "❌"}<br>`;
								msg += `• Meetings Access: ${p.meetings ? "✅" : "❌"}<br>`;
								msg += `• Calendar Access: ${p.calendar ? "✅" : "❌"}`;
								frappe.msgprint({
									title: __("Connection Test Successful"),
									message: msg,
									indicator: "green",
								});
							} else {
								frappe.msgprint({
									title: __("Connection Test Failed"),
									message: (r.message && r.message.message) || "Unknown error",
									indicator: "red",
								});
							}
						},
					});
				},
				__("More Actions")
			);

			frm.add_custom_button(
				__("View Statistics"),
				function () {
					frappe.call({
						method: "teams_integration.api.settings.get_teams_statistics",
						callback: function (r) {
							if (r.message) {
								const s = r.message;
								let msg = `<b>Teams Integration Statistics</b><br><br>
									📊 <b>Messages:</b><br>
									• Total: ${s.total_messages}<br>
									• Inbound: ${s.inbound_messages}<br>
									• Outbound: ${s.outbound_messages}<br><br>
									💬 <b>Conversations:</b><br>
									• Total: ${s.total_conversations}<br>
									• Unique Chats: ${s.unique_chats}<br><br>
									👥 <b>Employees with Azure ID:</b> ${s.employees_with_azure_id}`;
								if (s.recent_activity && s.recent_activity.length > 0) {
									msg += "<br><br><b>Recent Activity (Last 7 days):</b><br>";
									s.recent_activity.forEach(
										(a) => (msg += `• ${a.date}: ${a.count} messages<br>`)
									);
								}
								frappe.msgprint({
									title: __("Teams Integration Statistics"),
									message: msg,
									indicator: "blue",
									wide: true,
								});
							}
						},
					});
				},
				__("More Actions")
			);

			frm.add_custom_button(
				__("Validate Configuration"),
				function () {
					frappe.call({
						method: "teams_integration.api.settings.validate_configuration",
						callback: function (r) {
							if (r.message) {
								if (r.message.valid) {
									frappe.msgprint({
										title: __("Configuration Valid"),
										message: __("Your Teams integration configuration is correct!"),
										indicator: "green",
									});
								} else {
									let msg = "<b>Configuration Issues:</b><br>";
									r.message.issues.forEach((issue) => (msg += `• ${issue}<br>`));
									frappe.msgprint({
										title: __("Configuration Issues"),
										message: msg,
										indicator: "red",
									});
								}
							}
						},
					});
				},
				__("More Actions")
			);

			frm.add_custom_button(
				__("Reset Integration"),
				function () {
					frappe.warn(
						__("Reset Teams Integration"),
						__("This will clear all tokens. Are you absolutely sure?"),
						function () {
							frappe.call({
								method: "teams_integration.api.settings.reset_integration",
								callback: function (r) {
									if (!r.exc) {
										frm.reload_doc();
										frappe.msgprint({
											title: __("Integration Reset"),
											message: r.message,
											indicator: "orange",
										});
									}
								},
							});
						}
					);
				},
				__("More Actions")
			);

			frm.add_custom_button(
				__("Cleanup Old Messages"),
				function () {
					frappe.prompt(
						[
							{
								fieldname: "days",
								label: __("Delete messages older than (days)"),
								fieldtype: "Int",
								default: 30,
								reqd: 1,
							},
						],
						function (values) {
							frappe.confirm(
								__(
									`Permanently delete Teams messages older than ${values.days} days?`
								),
								function () {
									frappe.call({
										method: "teams_integration.api.settings.cleanup_old_messages",
										args: { days: values.days },
										callback: function (r) {
											if (!r.exc) {
												frappe.msgprint({
													title: __("Cleanup Complete"),
													message: r.message,
													indicator: "green",
												});
											}
										},
									});
								}
							);
						},
						__("Cleanup Messages"),
						__("Delete")
					);
				},
				__("More Actions")
			);

			// --- Sync Actions ---
			frm.add_custom_button(
				__("Sync All Conversations"),
				function () {
					frappe.confirm(
						__("Fetch recent messages from all your Teams chats? This may take a while."),
						function () {
							frappe.show_alert({ message: __("Syncing conversations..."), indicator: "blue" });
							frappe.call({
								method: "teams_integration.api.chat.sync_all_conversations",
								callback: function (r) {
									if (!r.exc && r.message) {
										frappe.msgprint({
											title: __("Sync Complete"),
											message: `Synced ${r.message.synced} conversations. ${r.message.errors} errors.`,
											indicator: "green",
										});
									}
								},
							});
						}
					);
				},
				__("Sync Actions")
			);

			frm.add_custom_button(
				__("Sync Azure IDs"),
				function () {
					frappe.confirm(
						__("Fetch all users from your Microsoft tenant and update Employee Azure IDs?"),
						function () {
							frappe.show_alert({ message: __("Syncing Azure IDs..."), indicator: "blue" });
							frappe.call({
								method: "teams_integration.api.settings.bulk_sync_azure_ids",
								callback: function (r) {
									if (!r.exc) {
										frappe.msgprint({
											title: __("Sync Complete"),
											message: r.message || __("Azure IDs synced successfully."),
											indicator: "green",
										});
									}
								},
							});
						}
					);
				},
				__("Sync Actions")
			);

			// Setup instructions
			frm.dashboard.add_section(
				`<div style="padding:10px;background:#f8f9fa;border-radius:5px;margin:10px 0;">
					<h5>Setup Instructions:</h5>
					<ol>
						<li>Configure your Microsoft Azure App registration credentials above</li>
						<li>Click <b>Authenticate with Teams</b> to authorize the app</li>
						<li>Use <b>Test Connection</b> to verify everything is working</li>
						<li>Add doctypes in the <b>Enabled Doctypes</b> table</li>
						<li>Use <b>Sync Azure IDs</b> to link Employees with Microsoft accounts</li>
					</ol>
				</div>`
			);
		}

		// Handle OAuth redirect status in URL
		const urlParams = new URLSearchParams(window.location.search);
		const authStatus = urlParams.get("teams_authentication_status");
		if (authStatus === "success") {
			frappe.show_alert({ message: __("Teams authentication successful!"), indicator: "green" }, 5);
			const cleanURL = new URL(window.location.href);
			cleanURL.searchParams.delete("teams_authentication_status");
			window.history.replaceState({}, document.title, cleanURL.pathname);
			setTimeout(() => frm.reload_doc(), 1000);
		} else if (authStatus === "error") {
			frappe.show_alert(
				{ message: __("Teams authentication failed. Please try again."), indicator: "red" },
				10
			);
			const cleanURL = new URL(window.location.href);
			cleanURL.searchParams.delete("teams_authentication_status");
			window.history.replaceState({}, document.title, cleanURL.pathname);
		}
	},

	redirect_uri: function (frm) {
		if (
			frm.doc.redirect_uri &&
			!frm.doc.redirect_uri.startsWith("http://") &&
			!frm.doc.redirect_uri.startsWith("https://")
		) {
			frappe.msgprint({
				title: __("Invalid Redirect URI"),
				message: __("Redirect URI must start with http:// or https://"),
				indicator: "red",
			});
		}
	},

	tenant_id: function (frm) {
		if (frm.doc.tenant_id) {
			const guidPattern =
				/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
			if (!guidPattern.test(frm.doc.tenant_id)) {
				frappe.msgprint({
					title: __("Invalid Tenant ID"),
					message: __(
						"Tenant ID should be in GUID format (e.g., 12345678-1234-1234-1234-123456789012)"
					),
					indicator: "orange",
				});
			}
		}
	},

	onload: function (frm) {
		if (frm.is_new() || !frm.doc.redirect_uri) {
			const defaultRedirectUri = `${window.location.origin}/api/method/teams_integration.api.auth.callback`;
			frm.set_value("redirect_uri", defaultRedirectUri);
		}
	},
});
