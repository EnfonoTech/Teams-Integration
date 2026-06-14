// Copyright (c) 2026, siva@enfono.com
// Teams Chat Page

frappe.pages["teams-chat"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Teams Chat"),
		single_column: true,
	});

	const page = wrapper.page;
	page.set_secondary_action(__("Sync All"), () => syncAll(page), "octicon octicon-sync");

	const $body = $(wrapper).find(".page-content");
	$body.empty().append(`
		<div id="ti-chat-wrap" style="display:flex;height:calc(100vh - 130px);border:1px solid var(--border-color);border-radius:6px;overflow:hidden;">
			<div id="ti-sidebar" style="width:280px;min-width:220px;border-right:1px solid var(--border-color);display:flex;flex-direction:column;background:var(--fg-color);">
				<div style="padding:10px 12px;border-bottom:1px solid var(--border-color);">
					<input id="ti-search" type="text" placeholder="${__("Search conversations...")}"
						style="width:100%;padding:5px 8px;border:1px solid var(--border-color);border-radius:4px;font-size:12px;background:var(--control-bg);">
				</div>
				<div id="ti-conv-list" style="flex:1;overflow-y:auto;padding:6px 0;"></div>
			</div>
			<div id="ti-main" style="flex:1;display:flex;flex-direction:column;background:var(--bg-color);">
				<div id="ti-chat-header" style="padding:10px 16px;border-bottom:1px solid var(--border-color);background:var(--fg-color);font-weight:600;font-size:14px;min-height:42px;">
					${__("Select a conversation")}
				</div>
				<div id="ti-messages" style="flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;">
					<div style="color:var(--text-muted);text-align:center;margin-top:40px;">${__("No conversation selected.")}</div>
				</div>
				<div id="ti-input-bar" style="padding:10px 12px;border-top:1px solid var(--border-color);background:var(--fg-color);display:flex;gap:8px;align-items:flex-end;">
					<textarea id="ti-msg-input" rows="2" placeholder="${__("Type a message…")}"
						style="flex:1;resize:none;padding:8px 10px;border:1px solid var(--border-color);border-radius:6px;font-size:13px;background:var(--control-bg);"></textarea>
					<button id="ti-send-btn" class="btn btn-primary btn-sm" style="height:36px;white-space:nowrap;">
						${__("Send")}
					</button>
				</div>
			</div>
		</div>
	`);

	let activeChatId = null;
	let activeConvType = "group";
	let activeDocType = null;
	let activeDocName = null;
	let activeLabel = null;
	let allConvs = [];

	// --- Load conversations ---
	function loadConversations() {
		frappe.call({
			method: "teams_integration.teams_integration.page.teams_chat.teams_chat.get_conversations",
			callback(r) {
				allConvs = r.message || [];
				renderConvList(allConvs);
			},
		});
	}

	function renderConvList(convs) {
		const $list = $("#ti-conv-list").empty();
		if (!convs.length) {
			$list.append(`<div style="padding:16px;color:var(--text-muted);font-size:12px;">${__("No conversations yet.")}</div>`);
			return;
		}

		const groups = convs.filter((c) => c.type === "group");
		const directs = convs.filter((c) => c.type === "direct");

		function section(title, items) {
			if (!items.length) return;
			$list.append(
				`<div style="padding:6px 12px 2px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.04em;">${__(title)}</div>`
			);
			items.forEach((conv) => {
				const isActive = conv.chat_id === activeChatId;
				$list.append(`
					<div class="ti-conv-item" data-chat="${conv.chat_id}" data-type="${conv.type}"
						data-dt="${conv.document_type || ""}" data-dn="${conv.document_name || ""}"
						data-label="${frappe.utils.escape_html(conv.label)}"
						style="padding:8px 14px;cursor:pointer;font-size:13px;
							border-left:3px solid ${isActive ? "var(--primary)" : "transparent"};
							background:${isActive ? "var(--subtle-accent)" : "transparent"};
							color:${isActive ? "var(--text-on-subtle-accent)" : "inherit"};">
						${frappe.utils.escape_html(conv.label)}
					</div>
				`);
			});
		}

		section("Group Chats", groups);
		section("Direct Messages", directs);

		$list.on("click", ".ti-conv-item", function () {
			const $el = $(this);
			activeChatId = $el.data("chat");
			activeConvType = $el.data("type");
			activeDocType = $el.data("dt") || null;
			activeDocName = $el.data("dn") || null;
			activeLabel = $el.data("label");
			renderConvList(allConvs); // re-render to update active highlight
			loadMessages();
		});
	}

	// --- Load messages ---
	function loadMessages() {
		if (!activeChatId) return;
		$("#ti-chat-header").text(activeLabel || activeChatId);
		const $msgs = $("#ti-messages").html(
			`<div style="text-align:center;color:var(--text-muted);padding:20px;">${__("Loading…")}</div>`
		);

		frappe.call({
			method: "teams_integration.api.chat.get_local_chat_messages",
			args: { chat_id: activeChatId, limit: 100 },
			callback(r) {
				const messages = r.message || [];
				$msgs.empty();
				if (!messages.length) {
					$msgs.html(
						`<div style="text-align:center;color:var(--text-muted);margin-top:40px;">${__("No messages. Send one or use Sync All.")}</div>`
					);
					return;
				}
				messages.forEach((msg) => renderMessage($msgs, msg));
				$msgs.scrollTop($msgs[0].scrollHeight);
			},
		});
	}

	function renderMessage($container, msg) {
		const isOut = msg.direction === "Outbound";
		const bubble = $(`
			<div style="display:flex;flex-direction:column;align-items:${isOut ? "flex-end" : "flex-start"};">
				<div style="font-size:11px;color:var(--text-muted);margin-bottom:2px;padding:0 4px;">
					${frappe.utils.escape_html(msg.sender_display)}
					<span style="margin-left:6px;">${msg.created_at ? msg.created_at.substring(0, 16) : ""}</span>
				</div>
				<div style="max-width:70%;padding:8px 12px;border-radius:${isOut ? "14px 4px 14px 14px" : "4px 14px 14px 14px"};
					background:${isOut ? "var(--primary)" : "var(--control-bg)"};
					color:${isOut ? "#fff" : "inherit"};
					font-size:13px;word-break:break-word;">
					${msg.body || ""}
				</div>
			</div>
		`);
		$container.append(bubble);
	}

	// --- Send message ---
	$("#ti-send-btn").on("click", sendMessage);
	$("#ti-msg-input").on("keydown", function (e) {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	});

	function sendMessage() {
		if (!activeChatId) {
			frappe.show_alert({ message: __("Select a conversation first."), indicator: "orange" });
			return;
		}
		const text = $("#ti-msg-input").val().trim();
		if (!text) return;

		$("#ti-msg-input").val("").prop("disabled", true);
		$("#ti-send-btn").prop("disabled", true);

		frappe.call({
			method: "teams_integration.api.chat.send_message_to_chat",
			args: {
				chat_id: activeChatId,
				message: text,
				docname: activeDocName,
				doctype: activeDocType,
			},
			callback(r) {
				$("#ti-msg-input").prop("disabled", false);
				$("#ti-send-btn").prop("disabled", false);
				if (r.message && r.message.success) {
					loadMessages();
				} else if (r.message && r.message.error === "auth_required") {
					frappe.confirm(
						__("Teams authentication required. Go to Teams Settings?"),
						() => frappe.set_route("Form", "Teams Settings", "Teams Settings")
					);
				}
			},
			error() {
				$("#ti-msg-input").prop("disabled", false);
				$("#ti-send-btn").prop("disabled", false);
			},
		});
	}

	// --- Sync all ---
	function syncAll(page) {
		page.set_indicator(__("Syncing…"), "blue");
		frappe.call({
			method: "teams_integration.api.chat.sync_all_conversations",
			callback(r) {
				page.set_indicator(__("Synced"), "green");
				if (activeChatId) loadMessages();
				setTimeout(() => page.clear_indicator(), 3000);
			},
		});
	}

	// --- Search filter ---
	$("#ti-search").on("input", function () {
		const q = this.value.toLowerCase();
		const filtered = q ? allConvs.filter((c) => c.label.toLowerCase().includes(q)) : allConvs;
		renderConvList(filtered);
	});

	// Feature 1: Real-time message push — auto-reload messages when a webhook fires
	frappe.realtime.on("teams_new_message", function (data) {
		if (data.chat_id === activeChatId) {
			loadMessages();
		} else {
			// Highlight the conversation in the sidebar with an unread dot
			$(`.ti-conv-item[data-chat="${data.chat_id}"]`).css("font-weight", "bold");
			frappe.show_alert({
				message: `${__("New Teams message from")} ${data.sender}`,
				indicator: "blue",
			});
		}
	});

	// Mark page as visited (resets unread badge)
	frappe.call({ method: "teams_integration.api.realtime_notify.mark_visited" });

	// Initial load
	loadConversations();
};
