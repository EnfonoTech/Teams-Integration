# Copyright (c) 2026, siva@enfono.com

import json
import frappe
import requests
from frappe import _
from frappe.utils import cstr
from .helpers import get_access_token, get_settings


@frappe.whitelist()
def get_enabled_doctypes():
	"""Get list of enabled doctypes for Teams integration."""
	try:
		settings = get_settings()
		return [
			row.doctype_name
			for row in (settings.enabled_doctypes or [])
			if row.doctype_name
		]
	except Exception as e:
		frappe.log_error(f"Error getting enabled doctypes: {str(e)}", "Teams Settings Error")
		return []


@frappe.whitelist()
def bulk_sync_azure_ids():
	"""Fetch all Microsoft tenant users and update their Azure IDs in Employee records."""
	try:
		settings = get_settings()
		token = get_access_token()

		if not token:
			frappe.throw("Please authenticate with Microsoft Teams first.")

		headers = {"Authorization": f"Bearer {token}"}
		all_users = []
		url = "https://graph.microsoft.com/v1.0/users"

		while url:
			response = requests.get(url, headers=headers, timeout=30)
			if response.status_code != 200:
				frappe.throw(f"Failed to fetch users from Microsoft Graph: {response.status_code}")
			data = response.json()
			all_users.extend(data.get("value", []))
			url = data.get("@odata.nextLink")

		if not all_users:
			frappe.msgprint("No users found in Microsoft Graph API")
			return "No users found to sync"

		updated_count = 0
		error_count = 0

		for graph_user in all_users:
			try:
				email = graph_user.get("mail") or graph_user.get("userPrincipalName")
				azure_id = graph_user.get("id")

				if not email or not azure_id:
					continue

				# Update Employee record(s) matching company_email or personal_email
				updated = False
				for field in ("company_email", "personal_email"):
					emp_name = frappe.db.get_value("Employee", {field: email}, "name")
					if emp_name:
						current_azure_id = frappe.db.get_value("Employee", emp_name, "azure_object_id")
						if current_azure_id != azure_id:
							frappe.db.set_value("Employee", emp_name, "azure_object_id", azure_id)
							updated = True

				if updated:
					updated_count += 1

			except Exception as user_error:
				frappe.log_error(f"Error processing user {email}: {str(user_error)}", "Teams User Sync Error")
				error_count += 1

		frappe.db.commit()

		# Update owner info in settings if not set
		if not settings.azure_owner_email_id and settings.access_token:
			try:
				me_response = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers, timeout=30)
				if me_response.status_code == 200:
					me_data = me_response.json()
					owner_email = me_data.get("mail") or me_data.get("userPrincipalName")
					owner_azure_id = me_data.get("id")
					if owner_email and owner_azure_id:
						settings.azure_owner_email_id = owner_email
						settings.owner_azure_object_id = owner_azure_id
						settings.save(ignore_permissions=True)
			except Exception as owner_error:
				frappe.log_error(f"Failed to update owner info: {str(owner_error)}", "Teams Owner Update Error")

		result_message = f"Sync completed: {updated_count} employees updated"
		if error_count > 0:
			result_message += f", {error_count} errors occurred"

		frappe.msgprint(result_message)
		return result_message

	except Exception as e:
		frappe.log_error(f"Bulk Azure ID sync failed: {str(e)}", "Teams Bulk Sync Error")
		frappe.throw(f"Failed to sync Azure IDs: {str(e)}")


@frappe.whitelist()
def test_teams_connection():
	"""Test connection to Microsoft Teams API and verify permissions."""
	try:
		token = get_access_token()
		if not token:
			return {"success": False, "message": "No access token available. Please authenticate first."}

		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
		me_response = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers, timeout=30)

		if me_response.status_code != 200:
			return {"success": False, "message": f"API connection failed: {me_response.status_code}"}

		user_data = me_response.json()
		chats_access = requests.get("https://graph.microsoft.com/v1.0/chats?$top=1", headers=headers, timeout=30).status_code in (200, 204)
		calendar_access = requests.get("https://graph.microsoft.com/v1.0/me/events?$top=1", headers=headers, timeout=30).status_code == 200

		dummy_meeting = {
			"startDateTime": "2025-01-01T12:00:00Z",
			"endDateTime": "2025-01-01T12:30:00Z",
			"subject": "Permission Test Meeting",
		}
		meetings_response = requests.post(
			"https://graph.microsoft.com/v1.0/me/onlineMeetings",
			headers=headers,
			json=dummy_meeting,
			timeout=30,
		)
		meetings_access = meetings_response.status_code == 201
		if meetings_access:
			meeting_id = meetings_response.json().get("id")
			if meeting_id:
				try:
					requests.delete(
						f"https://graph.microsoft.com/v1.0/me/onlineMeetings/{meeting_id}",
						headers=headers,
						timeout=30,
					)
				except Exception:
					pass

		return {
			"success": True,
			"message": "Connection successful",
			"user_info": {
				"name": user_data.get("displayName"),
				"email": user_data.get("mail") or user_data.get("userPrincipalName"),
				"id": user_data.get("id"),
			},
			"permissions": {
				"chats": chats_access,
				"meetings": meetings_access,
				"calendar": calendar_access,
			},
		}

	except Exception as e:
		frappe.log_error(f"Teams connection test failed: {str(e)}", "Teams Connection Test Error")
		return {"success": False, "message": f"Connection test failed: {str(e)}"}


@frappe.whitelist()
def get_teams_statistics():
	"""Get statistics about Teams integration usage."""
	try:
		stats = {
			"total_conversations": frappe.db.count("Teams Conversation"),
			"total_messages": frappe.db.count("Teams Chat Message"),
			"inbound_messages": frappe.db.count("Teams Chat Message", {"direction": "Inbound"}),
			"outbound_messages": frappe.db.count("Teams Chat Message", {"direction": "Outbound"}),
			"unique_chats": frappe.db.sql(
				"SELECT COUNT(DISTINCT chat_id) FROM `tabTeams Chat Message`"
			)[0][0],
			"employees_with_azure_id": frappe.db.count(
				"Employee", {"azure_object_id": ["!=", ""]}
			),
		}

		stats["recent_activity"] = frappe.db.sql(
			"""
			SELECT DATE(created_at) as date, COUNT(*) as count
			FROM `tabTeams Chat Message`
			WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
			GROUP BY DATE(created_at)
			ORDER BY date DESC
			""",
			as_dict=True,
		)

		stats["top_chats"] = frappe.db.sql(
			"""
			SELECT chat_id, COUNT(*) as message_count, MAX(created_at) as last_activity
			FROM `tabTeams Chat Message`
			GROUP BY chat_id
			ORDER BY message_count DESC
			LIMIT 5
			""",
			as_dict=True,
		)

		return stats

	except Exception as e:
		frappe.log_error(f"Error getting Teams statistics: {str(e)}", "Teams Statistics Error")
		return {}


@frappe.whitelist()
def cleanup_old_messages(days=30):
	"""Delete Teams messages older than the specified number of days."""
	try:
		days = int(days)
		if days < 1:
			frappe.throw("Days must be a positive integer")

		frappe.db.sql(
			"DELETE FROM `tabTeams Chat Message` WHERE created_at < DATE_SUB(NOW(), INTERVAL %s DAY)",
			(days,),
		)
		frappe.db.commit()

		message = f"Deleted messages older than {days} days"
		frappe.msgprint(message)
		return message

	except Exception as e:
		frappe.log_error(f"Error cleaning up old messages: {str(e)}", "Teams Cleanup Error")
		frappe.throw(f"Failed to cleanup old messages: {str(e)}")


@frappe.whitelist()
def export_chat_history(chat_id=None, format="json"):
	"""Export chat history for backup or analysis."""
	try:
		filters = {"chat_id": chat_id} if chat_id else {}
		messages = frappe.get_all(
			"Teams Chat Message",
			filters=filters,
			fields=["*"],
			order_by="created_at asc",
		)

		if format.lower() == "csv":
			import csv, io
			output = io.StringIO()
			writer = csv.DictWriter(output, fieldnames=messages[0].keys() if messages else [])
			writer.writeheader()
			writer.writerows(messages)
			return {
				"data": output.getvalue(),
				"filename": f"teams_chat_export_{chat_id or 'all'}_{frappe.utils.now()}.csv",
				"content_type": "text/csv",
			}

		return {
			"data": json.dumps(messages, indent=2, default=str),
			"filename": f"teams_chat_export_{chat_id or 'all'}_{frappe.utils.now()}.json",
			"content_type": "application/json",
		}

	except Exception as e:
		frappe.log_error(f"Error exporting chat history: {str(e)}", "Teams Export Error")
		frappe.throw(f"Failed to export chat history: {str(e)}")


@frappe.whitelist()
def validate_configuration():
	"""Validate Teams integration configuration."""
	try:
		settings = get_settings()
		issues = []

		required_fields = {
			"client_id": "Client ID",
			"client_secret": "Client Secret",
			"tenant_id": "Tenant ID",
			"redirect_uri": "Redirect URI",
		}

		for field, label in required_fields.items():
			value = getattr(settings, field, None)
			if not value:
				issues.append(f"Missing {label}")
			elif len(cstr(value).strip()) < 5:
				issues.append(f"{label} appears too short")

		if settings.redirect_uri:
			if not settings.redirect_uri.startswith(("http://", "https://")):
				issues.append("Redirect URI must start with http:// or https://")
			site_url = frappe.utils.get_url()
			if not settings.redirect_uri.startswith(site_url):
				issues.append("Redirect URI should point to current site")

		token = get_access_token()
		if not token:
			issues.append("Not authenticated with Microsoft Teams")
		else:
			try:
				response = requests.get(
					"https://graph.microsoft.com/v1.0/me",
					headers={"Authorization": f"Bearer {token}"},
					timeout=10,
				)
				if response.status_code != 200:
					issues.append("Access token appears to be invalid")
			except Exception:
				issues.append("Unable to validate access token")

		if not get_enabled_doctypes():
			issues.append("No doctypes enabled for Teams integration")

		return {
			"valid": len(issues) == 0,
			"issues": issues,
			"configuration_complete": len(issues) == 0,
		}

	except Exception as e:
		frappe.log_error(f"Configuration validation error: {str(e)}", "Teams Config Validation Error")
		return {"valid": False, "issues": ["Configuration validation failed"], "configuration_complete": False}


@frappe.whitelist()
def reset_integration():
	"""Reset Teams integration — clear all tokens."""
	try:
		settings = get_settings()
		settings.access_token = ""
		settings.refresh_token = ""
		settings.token_expiry = None
		settings.azure_owner_email_id = ""
		settings.owner_azure_object_id = ""
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_cache()
		return "Teams integration has been reset. Please reconfigure and authenticate."
	except Exception as e:
		frappe.log_error(f"Error resetting integration: {str(e)}", "Teams Reset Error")
		frappe.throw(f"Failed to reset integration: {str(e)}")


@frappe.whitelist()
def get_oauth_scopes():
	"""Return the list of OAuth scopes required for this integration."""
	return [
		"User.Read",
		"User.ReadBasic.All",
		"OnlineMeetings.ReadWrite",
		"offline_access",
		"Chat.ReadWrite",
		"Chat.Create",
		"Chat.ReadBasic",
		"ChannelMessage.Send",
		"Chat.ReadWrite.All",
		"Calendars.ReadWrite",
	]
