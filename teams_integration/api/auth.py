# Copyright (c) 2026, siva@enfono.com

import frappe
import requests
import json
from datetime import datetime, timedelta
from werkzeug.wrappers import Response
from werkzeug.exceptions import HTTPException
from frappe.utils import now_datetime
from .helpers import get_settings, get_access_token

GRAPH_API = "https://graph.microsoft.com/v1.0"


@frappe.whitelist(allow_guest=True)
def callback(code=None, state=None, error=None, error_description=None):
	"""Handle OAuth callback from Microsoft"""

	if error:
		frappe.log_error(f"OAuth Error: {error} - {error_description}", "Teams OAuth Error")
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = "/app/teams-settings?teams_authentication_status=error"
		return

	if not code:
		frappe.throw("Authorization code is missing from callback")

	try:
		settings = get_settings()

		if not all([settings.client_id, settings.client_secret, settings.tenant_id, settings.redirect_uri]):
			frappe.throw("Teams integration is not properly configured. Please check your settings.")

		token_url = f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/token"
		data = {
			"client_id": settings.client_id,
			"client_secret": settings.client_secret,
			"grant_type": "authorization_code",
			"code": code,
			"redirect_uri": settings.redirect_uri,
			"scope": "https://graph.microsoft.com/.default",
		}

		response = requests.post(
			token_url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data, timeout=30
		)

		if response.status_code != 200:
			error_data = response.json() if "application/json" in response.headers.get("content-type", "") else response.text
			frappe.log_error(f"Token exchange failed: {response.status_code} - {error_data}", "Teams Token Exchange Error")
			frappe.throw("Failed to authenticate with Microsoft Teams. Please try again.")

		# --- Per-employee OAuth flow ---
		if state and state.startswith("employee::"):
			employee_name = state.split("::", 1)[1]
			try:
				from .employee_auth import save_employee_tokens
				save_employee_tokens(employee_name, code, settings)
			except Exception as e:
				frappe.log_error(
					f"Employee token save failed for {employee_name}: {str(e)}",
					"Teams Employee OAuth Error",
				)
				frappe.local.response["type"] = "redirect"
				frappe.local.response["location"] = (
					f"/app/employee/{frappe.utils.escape_html(employee_name)}"
					"?teams_employee_auth=error"
				)
				return

			frappe.local.response["type"] = "redirect"
			frappe.local.response["location"] = (
				f"/app/employee/{frappe.utils.escape_html(employee_name)}"
				"?teams_employee_auth=success"
			)
			return

		# --- Admin / shared token flow ---
		token_data = response.json()
		settings.access_token = token_data.get("access_token")
		settings.refresh_token = token_data.get("refresh_token")
		expires_in = token_data.get("expires_in", 3600)
		settings.token_expiry = now_datetime() + timedelta(seconds=expires_in - 300)
		settings.save(ignore_permissions=True)
		frappe.db.commit()

		# Fetch user info and cache in Employee
		try:
			user_info_response = requests.get(
				f"{GRAPH_API}/me",
				headers={"Authorization": f"Bearer {settings.access_token}"},
				timeout=30,
			)

			if user_info_response.status_code == 200:
				user_info = user_info_response.json()
				azure_id = user_info.get("id")
				user_email = user_info.get("mail") or user_info.get("userPrincipalName")

				if azure_id and user_email:
					from .helpers import _cache_azure_id_in_employee
					_cache_azure_id_in_employee(user_email, azure_id)

					if not settings.azure_owner_email_id:
						settings.azure_owner_email_id = user_email
						settings.owner_azure_object_id = azure_id
						settings.save(ignore_permissions=True)
					frappe.db.commit()

		except Exception as e:
			frappe.log_error(f"Failed to fetch user info: {str(e)}", "Teams User Info Error")

		redirect_url = "/app/teams-settings?teams_authentication_status=success"
		if state and state.startswith("from_create_button::"):
			doc_name = state.replace("from_create_button::", "")
			if doc_name and doc_name != "Teams Settings":
				redirect_url = f"/app/event/{doc_name}?teams_authentication_status=success"

		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = redirect_url

	except Exception as e:
		frappe.log_error(f"Authentication callback error: {str(e)}", "Teams Authentication Error")
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = "/app/teams-settings?teams_authentication_status=error"


@frappe.whitelist()
def get_authentication_status():
	"""Check if Teams integration is properly authenticated"""
	try:
		settings = get_settings()

		if not settings.access_token:
			return {"authenticated": False, "message": "No access token found"}

		if settings.token_expiry and settings.token_expiry < now_datetime():
			return {"authenticated": False, "message": "Token expired"}

		response = requests.get(
			f"{GRAPH_API}/me",
			headers={"Authorization": f"Bearer {settings.access_token}"},
			timeout=10,
		)

		if response.status_code == 200:
			return {"authenticated": True, "message": "Authentication successful"}
		return {"authenticated": False, "message": "Token validation failed"}

	except Exception as e:
		frappe.log_error(f"Authentication status check failed: {str(e)}", "Teams Auth Status Error")
		return {"authenticated": False, "message": "Authentication check failed"}


@frappe.whitelist()
def revoke_authentication():
	"""Revoke Teams authentication and clear tokens"""
	try:
		settings = get_settings()
		settings.access_token = ""
		settings.refresh_token = ""
		settings.token_expiry = None
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		return {"success": True, "message": "Authentication revoked successfully"}
	except Exception as e:
		frappe.log_error(f"Failed to revoke authentication: {str(e)}", "Teams Auth Revoke Error")
		frappe.throw("Failed to revoke authentication")


# ---------------------------------------------------------------------------
# Webhook / Subscription Management
# ---------------------------------------------------------------------------

class GraphValidationResponse(HTTPException):
	def __init__(self, token):
		super().__init__()
		self.response = Response(token, status=200, mimetype="text/plain")


class GraphAcceptedResponse(HTTPException):
	def __init__(self):
		super().__init__()
		self.response = Response("Accepted", status=202, mimetype="text/plain")


@frappe.whitelist(allow_guest=True)
def handle_graph_webhook(**kwargs):
	"""Main listener for Microsoft Graph API Subscriptions."""
	_ = frappe.request.get_data()

	token = frappe.request.args.get("validationToken") or frappe.form_dict.get("validationToken")
	if token:
		raise GraphValidationResponse(token)

	try:
		frappe.local.flags.ignore_csrf = True
		payload = frappe.request.get_json()

		if payload and "value" in payload:
			for notification in payload.get("value", []):
				resource_url = notification.get("resource")
				if resource_url:
					frappe.enqueue(
						"teams_integration.api.auth.process_rsvp_change",
						resource_url=resource_url,
						queue="short",
					)
	except Exception as e:
		frappe.log_error(message=str(e), title="Webhook Payload Error")

	raise GraphAcceptedResponse()


@frappe.whitelist()
def subscribe_to_calendar_events():
	"""Tell Microsoft Graph to send webhooks when calendar events are updated."""
	token = get_access_token()
	if not token:
		frappe.throw("Authentication required.")

	notification_url = frappe.utils.get_url(
		"/api/method/teams_integration.api.auth.handle_graph_webhook"
	)
	expiration_time = datetime.utcnow() + timedelta(days=2)

	payload = {
		"changeType": "updated",
		"notificationUrl": notification_url,
		"resource": "/me/events",
		"expirationDateTime": expiration_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
		"clientState": "TeamsIntegrationSyncV1",
	}

	res = requests.post(
		f"{GRAPH_API}/subscriptions",
		headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
		json=payload,
	)

	if res.status_code == 201:
		data = res.json()
		return {"success": True, "subscription_id": data.get("id")}

	frappe.log_error(message=res.text, title="Graph Webhook Error")
	frappe.throw(f"Failed to subscribe: {res.status_code}")


def process_rsvp_change(resource_url):
	"""Background job: fetch updated event and sync RSVP statuses to Frappe Event."""
	try:
		token = get_access_token()
		if not token:
			return

		url = resource_url if resource_url.startswith("https") else f"{GRAPH_API}/{resource_url.lstrip('/')}"
		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

		res = requests.get(url, headers=headers, timeout=30)
		if res.status_code != 200:
			frappe.log_error(message=res.text, title="RSVP Sync Error")
			return

		event_data = res.json()
		outlook_event_id = event_data.get("id")
		attendees = event_data.get("attendees", [])

		if not outlook_event_id or not attendees:
			return

		event_name = frappe.db.get_value(
			"Event", {"custom_outlook_event_id": outlook_event_id}, "name"
		)
		if not event_name:
			return

		status_map = {"accepted": "Yes", "declined": "No", "tentative": "Maybe"}
		attendee_responses = {}

		for a in attendees:
			email = a.get("emailAddress", {}).get("address", "").lower()
			status = a.get("status", {}).get("response", "").lower()
			if email and status in status_map:
				attendee_responses[email] = status_map[status]

		doc = frappe.get_doc("Event", event_name)
		doc_updated = False

		for row in doc.event_participants:
			row_email = (row.email or "").lower()
			if row_email in attendee_responses:
				new_status = attendee_responses[row_email]
				if row.attending != new_status:
					row.attending = new_status
					doc_updated = True

		if doc_updated:
			doc.flags.ignore_validate = True
			doc.flags.ignore_permissions = True
			doc.save()
			frappe.db.commit()

	except Exception as e:
		frappe.log_error(message=str(e), title="RSVP Processing Error")


def renew_graph_subscriptions():
	"""Daily cron: keep the Microsoft Graph Webhook subscription alive."""
	try:
		token = get_access_token()
		if not token:
			return

		settings = frappe.get_single("Teams Settings")
		sub_id = settings.get("custom_webhook_subscription_id")

		headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

		if sub_id:
			expiration_time = datetime.utcnow() + timedelta(days=2)
			res = requests.patch(
				f"{GRAPH_API}/subscriptions/{sub_id}",
				headers=headers,
				json={"expirationDateTime": expiration_time.strftime("%Y-%m-%dT%H:%M:%SZ")},
			)
			if res.status_code == 200:
				return
			frappe.log_error(message=res.text, title="Webhook Renewal Warning")

		result = subscribe_to_calendar_events()
		if result and result.get("success"):
			settings.db_set("custom_webhook_subscription_id", result.get("subscription_id"))
			frappe.db.commit()

	except Exception as e:
		frappe.log_error(
			message=frappe.get_traceback(),
			title=f"Webhook Renewal Error: {str(e)}"[:135],
		)
