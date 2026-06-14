# Copyright (c) 2026, siva@enfono.com

import frappe
import requests
import html
from datetime import datetime
from frappe.utils import now_datetime, sanitize_html
from .helpers import get_access_token, get_azure_user_id_by_email, get_login_url

GRAPH_API = "https://graph.microsoft.com/v1.0"

SUPPORTED_DOCTYPES = {
	"Event": {
		"participants_field": "event_participants",
		"email_field": "email",
		"subject_field": "subject",
	},
	"Project": {
		"participants_field": "users",
		"email_field": "email",
		"subject_field": "project_name",
	},
}


def get_my_azure_id():
	"""Get the authenticated owner's Azure ID from Teams Settings."""
	try:
		settings = frappe.get_single("Teams Settings")
		if settings.owner_azure_object_id:
			return settings.owner_azure_object_id
		# Fall back to current user's employee record
		current_user = frappe.session.user
		if current_user != "Guest":
			user_email = frappe.db.get_value("User", current_user, "email")
			if user_email:
				from .helpers import _get_azure_id_from_employee
				return _get_azure_id_from_employee(user_email)
		return None
	except Exception as e:
		frappe.log_error(f"Failed to get current user's Azure ID: {str(e)}", "Teams Azure ID Error")
		return None


@frappe.whitelist()
def create_group_chat_for_doc(docname, doctype):
	"""Create or update Teams group chat for a document."""
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(f"{doctype} is not supported for Teams chat creation.")

	try:
		doc = frappe.get_doc(doctype, docname)
		token = get_access_token()
		if not token:
			return {"error": "auth_required", "login_url": get_login_url(docname)}

		config = SUPPORTED_DOCTYPES[doctype]
		participants_field = config["participants_field"]
		email_field = config["email_field"]

		target_azure_ids = set()
		participants_data = getattr(doc, participants_field, None)
		if participants_data:
			for participant in participants_data:
				email_val = getattr(participant, email_field, None)
				if email_val:
					azure_id = get_azure_user_id_by_email(email_val)
					if azure_id:
						target_azure_ids.add(azure_id)

		my_azure_id = get_my_azure_id()
		if my_azure_id:
			target_azure_ids.add(my_azure_id)

		if not target_azure_ids:
			frappe.throw("No valid Microsoft Teams users found for chat creation.")

		existing_chat_id = getattr(doc, "custom_teams_chat_id", None)
		if existing_chat_id:
			return _update_existing_chat(existing_chat_id, target_azure_ids, token)
		return _create_new_chat(docname, doctype, target_azure_ids, token)

	except Exception as e:
		frappe.log_error(f"Error creating chat for {doctype} {docname}: {str(e)}", "Teams Chat Creation Error")
		frappe.throw(f"Failed to create Teams chat: {str(e)}")


def _update_existing_chat(chat_id, target_azure_ids, token):
	"""Add new members to an existing chat."""
	try:
		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
		response = requests.get(f"{GRAPH_API}/chats/{chat_id}/members", headers=headers, timeout=30)

		if response.status_code != 200:
			frappe.throw(f"Failed to fetch existing chat members: {response.status_code}")

		existing_ids = {
			m.get("userId") for m in response.json().get("value", []) if m.get("userId")
		}
		new_member_ids = target_azure_ids - existing_ids

		if not new_member_ids:
			return {"chat_id": chat_id, "message": "Chat is up to date with all participants."}

		added_count = 0
		for azure_id in new_member_ids:
			add_response = requests.post(
				f"{GRAPH_API}/chats/{chat_id}/members",
				headers=headers,
				json={
					"@odata.type": "#microsoft.graph.aadUserConversationMember",
					"roles": ["owner"],
					"user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{azure_id}')",
				},
				timeout=30,
			)
			if add_response.status_code in (200, 201):
				added_count += 1
			else:
				frappe.log_error(
					f"Failed to add member {azure_id}: {add_response.text}", "Teams Add Member Error"
				)

		return {"chat_id": chat_id, "message": f"Added {added_count} new member(s) to existing chat."}

	except Exception as e:
		frappe.log_error(f"Error updating existing chat {chat_id}: {str(e)}", "Teams Chat Update Error")
		frappe.throw(f"Failed to update existing chat: {str(e)}")


def _create_new_chat(docname, doctype, target_azure_ids, token):
	"""Create a brand-new Teams group chat and link it to the document."""
	try:
		members = [
			{
				"@odata.type": "#microsoft.graph.aadUserConversationMember",
				"roles": ["owner"],
				"user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{azure_id}')",
			}
			for azure_id in target_azure_ids
		]

		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
		response = requests.post(
			f"{GRAPH_API}/chats", headers=headers, json={"chatType": "group", "members": members}, timeout=30
		)

		if response.status_code not in (200, 201):
			frappe.throw(f"Failed to create Teams chat: {response.status_code}")

		chat_id = response.json().get("id")
		if not chat_id:
			frappe.throw("Failed to get chat ID from Teams response")

		if frappe.db.has_column(doctype, "custom_teams_chat_id"):
			frappe.db.set_value(doctype, docname, "custom_teams_chat_id", chat_id)

		frappe.get_doc({
			"doctype": "Teams Conversation",
			"chat_id": chat_id,
			"document_type": doctype,
			"document_name": docname,
			"last_synced": now_datetime(),
		}).insert(ignore_permissions=True)
		frappe.db.commit()

		return {"chat_id": chat_id, "message": "New Teams chat created successfully."}

	except Exception as e:
		frappe.log_error(f"Error creating new chat for {doctype} {docname}: {str(e)}", "Teams New Chat Error")
		frappe.throw(f"Failed to create new Teams chat: {str(e)}")


@frappe.whitelist()
def send_message_to_chat(chat_id, message, docname=None, doctype=None):
	"""Send a message to a Teams chat, attributed to the ERPNext user."""
	if not chat_id or not message:
		frappe.throw("Chat ID and message are required")

	try:
		token = get_access_token()
		if not token:
			return {"error": "auth_required", "message": "Authentication required"}

		actual_sender_name = frappe.utils.get_fullname(frappe.session.user)
		sanitized_message = html.escape(str(message))

		final_html_content = (
			f'<div style="color:#616161;font-size:12px;margin-bottom:4px;">'
			f"<strong>{actual_sender_name}</strong> via ERPNext:</div>"
			f"<div>{sanitized_message}</div>"
		)

		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
		payload = {"body": {"contentType": "html", "content": final_html_content}}

		response = requests.post(
			f"{GRAPH_API}/chats/{chat_id}/messages", headers=headers, json=payload, timeout=30
		)

		if response.status_code in (200, 201):
			message_data = response.json()
			_save_message_local(message_data, chat_id, docname, doctype, "Outbound")
			return {
				"success": True,
				"message_id": message_data.get("id"),
				"message": "Message sent successfully",
			}

		elif response.status_code == 401:
			try:
				from .helpers import refresh_access_token
				token = refresh_access_token()
				headers["Authorization"] = f"Bearer {token}"
				response = requests.post(
					f"{GRAPH_API}/chats/{chat_id}/messages", headers=headers, json=payload, timeout=30
				)
				if response.status_code in (200, 201):
					message_data = response.json()
					_save_message_local(message_data, chat_id, docname, doctype, "Outbound")
					return {"success": True, "message_id": message_data.get("id"), "message": "Message sent"}
			except Exception as refresh_error:
				frappe.log_error(f"Token refresh failed: {str(refresh_error)}", "Teams Token Refresh Error")

		frappe.log_error(f"Failed to send message: {response.status_code} - {response.text}", "Teams Send Message Error")
		frappe.throw(f"Failed to send message to Teams: {response.status_code}")

	except requests.exceptions.Timeout:
		frappe.throw("Message sending timed out. Please try again.")
	except Exception as e:
		frappe.log_error(f"Error sending message: {str(e)}", "Teams Send Message Error")
		frappe.throw(f"Failed to send message: {str(e)}")


@frappe.whitelist()
def get_local_chat_messages(chat_id, limit=200):
	"""Get chat messages from local database."""
	if not chat_id:
		return []

	try:
		limit = min(int(limit), 500)
		messages = frappe.get_all(
			"Teams Chat Message",
			filters={"chat_id": chat_id},
			fields=["message_id", "sender_display", "body", "created_at", "direction", "sender_id"],
			order_by="created_at desc",
			limit_page_length=limit,
		)

		for msg in messages:
			if msg.get("created_at"):
				msg["created_at"] = str(msg["created_at"])
			if msg.get("body"):
				msg["body"] = sanitize_html(msg["body"])

		return list(reversed(messages))

	except Exception as e:
		frappe.log_error(f"Error fetching local messages for chat {chat_id}: {str(e)}", "Teams Local Messages Error")
		return []


@frappe.whitelist()
def fetch_and_store_chat_messages(chat_id, docname=None, doctype=None, top=50):
	"""Fetch messages from Teams API and store locally."""
	if not chat_id:
		return None

	try:
		token = get_access_token()
		if not token:
			return None

		top = min(int(top), 100)
		headers = {"Authorization": f"Bearer {token}"}
		response = requests.get(
			f"{GRAPH_API}/chats/{chat_id}/messages?$top={top}", headers=headers, timeout=30
		)

		if response.status_code == 200:
			messages = response.json().get("value", [])
			stored_count = sum(
				1 for m in messages if _save_message_local(m, chat_id, docname, doctype, "Inbound")
			)
			return {"success": True, "fetched": len(messages), "stored": stored_count}

		frappe.log_error(f"Failed to fetch messages: {response.status_code} - {response.text}", "Teams Fetch Messages Error")
		return None

	except Exception as e:
		frappe.log_error(f"Error fetching messages for chat {chat_id}: {str(e)}", "Teams Fetch Messages Error")
		return None


def _save_message_local(msg_json, chat_id, docname=None, doctype=None, direction="Inbound"):
	"""Save a Teams message to local database, skipping duplicates."""
	try:
		if not msg_json or not isinstance(msg_json, dict):
			return False

		message_id = msg_json.get("id")
		if not message_id:
			return False

		if frappe.db.exists("Teams Chat Message", {"message_id": message_id}):
			return False

		body_data = msg_json.get("body", {})
		body_content = body_data.get("content", "") if isinstance(body_data, dict) else str(body_data)

		created_str = msg_json.get("createdDateTime")
		created_at = now_datetime()
		if created_str:
			try:
				if created_str.endswith("Z"):
					created_str = created_str[:-1] + "+00:00"
				created_at = datetime.fromisoformat(created_str).strftime("%Y-%m-%d %H:%M:%S")
			except (ValueError, AttributeError):
				created_at = now_datetime().strftime("%Y-%m-%d %H:%M:%S")

		sender_info = msg_json.get("from", {})
		sender_id = None
		sender_display = "Unknown"
		if isinstance(sender_info, dict):
			user_info = sender_info.get("user", {}) or {}
			sender_id = user_info.get("id") or sender_info.get("id")
			sender_display = user_info.get("displayName") or sender_info.get("displayName") or "Unknown"

		doc_data = {
			"doctype": "Teams Chat Message",
			"chat_id": chat_id,
			"message_id": message_id,
			"sender_id": sender_id,
			"sender_display": sender_display,
			"body": sanitize_html(body_content) if body_content else "",
			"created_at": created_at,
			"direction": direction,
		}

		if doctype and docname:
			doc_data["document_type"] = doctype
			doc_data["document_name"] = docname

		frappe.get_doc(doc_data).insert(ignore_permissions=True)
		frappe.db.commit()
		return True

	except Exception as e:
		frappe.log_error(f"Error saving Teams message {msg_json.get('id')}: {str(e)}", "Teams Message Save Error")
		return False


@frappe.whitelist()
def post_message_to_channel(team_id, channel_id, message, docname=None):
	"""Post a message to a Teams channel."""
	if not all([team_id, channel_id, message]):
		frappe.throw("Team ID, Channel ID, and message are required")

	try:
		token = get_access_token()
		if not token:
			return {"error": "auth_required", "message": "Authentication required"}

		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
		payload = {"body": {"contentType": "html", "content": html.escape(str(message))}}

		response = requests.post(
			f"{GRAPH_API}/teams/{team_id}/channels/{channel_id}/messages",
			headers=headers,
			json=payload,
			timeout=30,
		)

		if response.status_code in (200, 201):
			return {"success": True, "message": "Posted to channel successfully"}

		frappe.log_error(f"Failed to post to channel: {response.status_code} - {response.text}", "Teams Channel Post Error")
		frappe.throw(f"Failed to post to Teams channel: {response.status_code}")

	except Exception as e:
		frappe.log_error(f"Error posting to channel: {str(e)}", "Teams Channel Post Error")
		frappe.throw(f"Failed to post to channel: {str(e)}")


@frappe.whitelist()
def sync_all_conversations(chat_id=None):
	"""Sync Teams conversations — one specific chat or all known chats."""
	try:
		access_token = get_access_token()
		if not access_token:
			frappe.throw("Could not fetch Teams access token. Please authenticate first.")

		headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
		synced_count = 0
		error_count = 0

		if chat_id:
			if _sync_single_chat(chat_id, headers):
				synced_count = 1
			else:
				error_count = 1
		else:
			chats_response = requests.get(f"{GRAPH_API}/chats", headers=headers, timeout=30)
			if chats_response.status_code == 200:
				for chat in chats_response.json().get("value", []):
					cid = chat.get("id")
					if cid:
						if _sync_single_chat(cid, headers):
							synced_count += 1
						else:
							error_count += 1
			else:
				frappe.throw("Failed to fetch chats list from Teams")

		frappe.msgprint(f"Synced {synced_count} conversation(s). {error_count} errors.")
		return {"success": True, "synced": synced_count, "errors": error_count}

	except Exception as e:
		frappe.log_error(f"Error syncing conversations: {str(e)}", "Teams Sync Conversations Error")
		frappe.throw("Failed to sync Teams conversations. Check error logs for details.")


def _sync_single_chat(chat_id, headers):
	"""Sync a single chat's messages."""
	try:
		response = requests.get(
			f"{GRAPH_API}/chats/{chat_id}/messages?$top=50", headers=headers, timeout=30
		)
		if response.status_code == 200:
			for msg in response.json().get("value", []):
				_save_message_local(msg, chat_id, None, None, "Inbound")
			if frappe.db.exists("Teams Conversation", {"chat_id": chat_id}):
				frappe.db.set_value("Teams Conversation", {"chat_id": chat_id}, "last_synced", now_datetime())
			return True
		frappe.log_error(f"Failed to sync chat {chat_id}: {response.status_code}", "Teams Single Chat Sync Error")
		return False
	except Exception as e:
		frappe.log_error(f"Error syncing single chat {chat_id}: {str(e)}", "Teams Single Chat Sync Error")
		return False


@frappe.whitelist()
def send_employee_direct_message(to_email, message):
	"""Send a 1:1 Teams message AS the currently logged-in employee (using their personal token).
	Both the sender and recipient must have personal tokens or synced Azure IDs."""
	if not to_email or not message:
		frappe.throw("Target email and message are required")

	try:
		# Resolve sender's Employee
		current_user = frappe.session.user
		sender_email = frappe.db.get_value("User", current_user, "email")
		sender_emp = (
			frappe.db.get_value("Employee", {"user_id": current_user}, "name")
			or frappe.db.get_value("Employee", {"company_email": sender_email}, "name")
			or frappe.db.get_value("Employee", {"personal_email": sender_email}, "name")
		)
		if not sender_emp:
			frappe.throw("No Employee record linked to your account.")

		from .employee_auth import get_employee_token
		token = get_employee_token(sender_emp)
		if not token:
			return {
				"error": "employee_auth_required",
				"employee_name": sender_emp,
				"message": "Connect your Teams account first from your Employee form.",
			}

		from .helpers import _get_azure_id_from_employee
		my_azure_id = _get_azure_id_from_employee(sender_email)
		target_azure_id = get_azure_user_id_by_email(to_email)

		if not my_azure_id:
			frappe.throw("Your Azure Object ID is not set. Sync it from your Employee form first.")
		if not target_azure_id:
			frappe.throw(f"Could not find Microsoft account for {to_email}.")

		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

		# Create/retrieve 1:1 chat using the sender's personal token
		chat_payload = {
			"chatType": "oneOnOne",
			"members": [
				{
					"@odata.type": "#microsoft.graph.aadUserConversationMember",
					"roles": ["owner"],
					"user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{my_azure_id}')",
				},
				{
					"@odata.type": "#microsoft.graph.aadUserConversationMember",
					"roles": ["owner"],
					"user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{target_azure_id}')",
				},
			],
		}
		chat_resp = requests.post(f"{GRAPH_API}/chats", headers=headers, json=chat_payload, timeout=30)
		if chat_resp.status_code not in (200, 201):
			frappe.throw(f"Could not establish chat channel: {chat_resp.status_code}")

		chat_id = chat_resp.json().get("id")

		# Send the message using the sender's identity — no admin prefix needed
		import html as _html
		msg_payload = {
			"body": {"contentType": "text", "content": str(message)}
		}
		send_resp = requests.post(
			f"{GRAPH_API}/chats/{chat_id}/messages", headers=headers, json=msg_payload, timeout=30
		)
		if send_resp.status_code in (200, 201):
			msg_data = send_resp.json()
			_save_message_local(msg_data, chat_id, None, None, "Outbound")
			return {"success": True, "chat_id": chat_id, "message_id": msg_data.get("id")}

		frappe.throw(f"Failed to send message: {send_resp.status_code}")

	except Exception as e:
		frappe.log_error(
			f"Error sending employee direct message to {to_email}: {str(e)}",
			"Teams Employee Direct Message Error",
		)
		frappe.throw(f"Failed to send message: {str(e)}")


@frappe.whitelist()
def create_direct_chat(to_email):
	"""Create or retrieve a 1:1 Teams chat with a specific user. Microsoft Graph is
	idempotent — calling this twice with the same two parties returns the same chat."""
	if not to_email:
		frappe.throw("Target email is required")

	try:
		token = get_access_token()
		if not token:
			return {"error": "auth_required", "login_url": get_login_url()}

		my_azure_id = get_my_azure_id()
		if not my_azure_id:
			frappe.throw(
				"Your Azure ID could not be resolved. Open your Employee record and click "
				"Teams → Sync Teams Azure ID, then try again."
			)

		target_azure_id = get_azure_user_id_by_email(to_email)
		if not target_azure_id:
			frappe.throw(
				f"No Microsoft account found for {to_email}. "
				"Ensure the employee's Azure ID has been synced."
			)

		if my_azure_id == target_azure_id:
			frappe.throw("Cannot create a direct chat with yourself.")

		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
		payload = {
			"chatType": "oneOnOne",
			"members": [
				{
					"@odata.type": "#microsoft.graph.aadUserConversationMember",
					"roles": ["owner"],
					"user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{my_azure_id}')",
				},
				{
					"@odata.type": "#microsoft.graph.aadUserConversationMember",
					"roles": ["owner"],
					"user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{target_azure_id}')",
				},
			],
		}

		response = requests.post(f"{GRAPH_API}/chats", headers=headers, json=payload, timeout=30)

		if response.status_code not in (200, 201):
			frappe.log_error(
				f"Failed to create direct chat with {to_email}: {response.status_code} - {response.text}",
				"Teams Direct Chat Error",
			)
			frappe.throw(f"Failed to create direct chat: {response.status_code}")

		chat_id = response.json().get("id")
		if not chat_id:
			frappe.throw("No chat ID returned from Teams API")

		# Link to the target employee in Teams Conversation for message history
		if not frappe.db.exists("Teams Conversation", {"chat_id": chat_id}):
			emp_name = (
				frappe.db.get_value("Employee", {"company_email": to_email}, "name")
				or frappe.db.get_value("Employee", {"personal_email": to_email}, "name")
			)
			frappe.get_doc({
				"doctype": "Teams Conversation",
				"chat_id": chat_id,
				"topic": f"Direct: {to_email}",
				"document_type": "Employee" if emp_name else None,
				"document_name": emp_name or None,
				"last_synced": now_datetime(),
			}).insert(ignore_permissions=True)
			frappe.db.commit()

		return {"chat_id": chat_id, "message": "Direct chat ready."}

	except Exception as e:
		frappe.log_error(f"Error creating direct chat with {to_email}: {str(e)}", "Teams Direct Chat Error")
		frappe.throw(f"Failed to create direct chat: {str(e)}")


@frappe.whitelist()
def send_direct_message(to_email, message):
	"""Send a 1:1 direct message to an employee via Teams."""
	if not to_email or not message:
		frappe.throw("Target email and message are required")

	try:
		result = create_direct_chat(to_email)
		if isinstance(result, dict) and result.get("error") == "auth_required":
			return result

		chat_id = result.get("chat_id") if isinstance(result, dict) else None
		if not chat_id:
			frappe.throw("Could not establish direct chat channel.")

		return send_message_to_chat(chat_id, message)

	except Exception as e:
		frappe.log_error(f"Error sending direct message to {to_email}: {str(e)}", "Teams Direct Message Error")
		frappe.throw(f"Failed to send direct message: {str(e)}")


@frappe.whitelist()
def get_direct_chat_messages(to_email, limit=50):
	"""Get the latest messages from a 1:1 chat with an employee, syncing from Teams first."""
	if not to_email:
		frappe.throw("Target email is required")

	try:
		result = create_direct_chat(to_email)
		if isinstance(result, dict) and result.get("error") == "auth_required":
			return result

		chat_id = result.get("chat_id") if isinstance(result, dict) else None
		if not chat_id:
			frappe.throw("Could not resolve direct chat channel.")

		# Pull latest messages from Teams so the history is fresh
		fetch_and_store_chat_messages(chat_id, top=min(int(limit), 100))

		return get_local_chat_messages(chat_id, limit=limit)

	except Exception as e:
		frappe.log_error(f"Error getting direct chat messages with {to_email}: {str(e)}", "Teams Direct Chat Error")
		frappe.throw(f"Failed to fetch direct chat messages: {str(e)}")


@frappe.whitelist()
def get_chat_statistics(chat_id=None):
	"""Get statistics about Teams chat messages."""
	try:
		filters = {"chat_id": chat_id} if chat_id else {}
		return {
			"total_messages": frappe.db.count("Teams Chat Message", filters),
			"inbound_messages": frappe.db.count("Teams Chat Message", {**filters, "direction": "Inbound"}),
			"outbound_messages": frappe.db.count("Teams Chat Message", {**filters, "direction": "Outbound"}),
		}
	except Exception as e:
		frappe.log_error(f"Error getting chat statistics: {str(e)}", "Teams Stats Error")
		return {}
