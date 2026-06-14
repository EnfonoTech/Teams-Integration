# Copyright (c) 2026, siva@enfono.com

import frappe
import requests
import urllib.parse
from datetime import timedelta
from frappe.utils import now_datetime, get_datetime

GRAPH_API = "https://graph.microsoft.com/v1.0"


def get_settings():
	"""Get Teams Settings singleton"""
	try:
		return frappe.get_doc("Teams Settings")
	except frappe.DoesNotExistError:
		frappe.throw("Teams Settings not found. Please configure Teams integration first.")
	except Exception as e:
		frappe.log_error(f"Failed to get Teams settings: {str(e)}", "Teams Settings Error")
		frappe.throw("Failed to load Teams settings")


@frappe.whitelist()
def get_access_token():
	"""Get valid access token, refreshing if it expires within 5 minutes"""
	try:
		settings = get_settings()

		if not settings.access_token:
			return None

		if settings.token_expiry:
			expiry_time = get_datetime(settings.token_expiry)
			current_time = now_datetime()
			if (expiry_time - current_time).total_seconds() < 300:
				try:
					return refresh_access_token()
				except Exception as e:
					frappe.log_error(f"Token refresh failed: {str(e)}", "Teams Token Refresh Error")
					return None

		return settings.access_token

	except Exception as e:
		frappe.log_error(f"Failed to get access token: {str(e)}", "Teams Token Error")
		return None


@frappe.whitelist()
def refresh_access_token():
	"""Refresh access token using the stored refresh token"""
	try:
		settings = get_settings()

		if not settings.refresh_token:
			frappe.throw("No refresh token available. Please re-authenticate.")

		token_url = f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/token"
		data = {
			"client_id": settings.client_id,
			"client_secret": settings.client_secret,
			"grant_type": "refresh_token",
			"refresh_token": settings.refresh_token,
			"scope": "https://graph.microsoft.com/.default",
		}

		response = requests.post(
			token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30
		)

		if response.status_code != 200:
			error_data = response.text
			try:
				error_data = response.json().get("error_description", error_data)
			except Exception:
				pass
			frappe.log_error(
				f"Token refresh failed: {response.status_code} - {error_data}", "Teams Token Refresh Error"
			)
			if response.status_code == 400:
				settings.access_token = ""
				settings.refresh_token = ""
				settings.token_expiry = None
				settings.save(ignore_permissions=True)
				frappe.db.commit()
			frappe.throw("Failed to refresh access token. Please re-authenticate.")

		token_data = response.json()
		settings.access_token = token_data.get("access_token")
		if token_data.get("refresh_token"):
			settings.refresh_token = token_data.get("refresh_token")

		expires_in = token_data.get("expires_in", 3600)
		settings.token_expiry = now_datetime() + timedelta(seconds=expires_in - 300)
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_cache(doctype="Teams Settings")

		return settings.access_token

	except requests.exceptions.Timeout:
		frappe.throw("Authentication request timed out. Please try again.")
	except requests.exceptions.RequestException as e:
		frappe.log_error(f"Network error during token refresh: {str(e)}", "Teams Token Refresh Network Error")
		frappe.throw("Network error during authentication.")
	except Exception as e:
		frappe.log_error(f"Unexpected error during token refresh: {str(e)}", "Teams Token Refresh Error")
		frappe.throw("An unexpected error occurred during authentication.")


def _get_azure_id_from_employee(email):
	"""Look up cached Azure Object ID from the Employee doctype by email."""
	if not email:
		return None
	# ERPNext Employee has company_email and personal_email
	emp = frappe.db.get_value(
		"Employee",
		{"company_email": email},
		["name", "azure_object_id"],
		as_dict=True,
	)
	if emp and emp.get("azure_object_id"):
		return emp.azure_object_id

	emp = frappe.db.get_value(
		"Employee",
		{"personal_email": email},
		["name", "azure_object_id"],
		as_dict=True,
	)
	if emp and emp.get("azure_object_id"):
		return emp.azure_object_id

	return None


def _cache_azure_id_in_employee(email, azure_id):
	"""Persist the fetched Azure ID back into the matching Employee record."""
	if not email or not azure_id:
		return
	for field in ("company_email", "personal_email"):
		emp_name = frappe.db.get_value("Employee", {field: email}, "name")
		if emp_name:
			try:
				frappe.db.set_value("Employee", emp_name, "azure_object_id", azure_id)
				frappe.db.commit()
			except Exception as e:
				frappe.log_error(f"Failed to cache Azure ID for {email}: {str(e)}", "Teams Cache Error")
			return


@frappe.whitelist()
def get_azure_user_id_by_email(email):
	"""Get Azure user ID by email — checks Employee first, then falls back to Graph API."""
	if not email:
		return None

	# 1. Check Employee record (avoids a Graph API call)
	cached = _get_azure_id_from_employee(email)
	if cached:
		return cached

	# 2. Fetch from Azure AD
	token = get_access_token()
	if not token:
		frappe.log_error(f"No access token to fetch Azure ID for {email}", "Teams API Error")
		return None

	headers = {"Authorization": f"Bearer {token}"}
	encoded_email = urllib.parse.quote(email, safe="")
	url = f"{GRAPH_API}/users/{encoded_email}"

	try:
		response = requests.get(url, headers=headers, timeout=10)

		if response.status_code == 200:
			azure_id = response.json().get("id")
			if azure_id:
				_cache_azure_id_in_employee(email, azure_id)
			return azure_id

		elif response.status_code == 401:
			try:
				token = refresh_access_token()
				headers["Authorization"] = f"Bearer {token}"
				response = requests.get(url, headers=headers, timeout=10)
				if response.status_code == 200:
					azure_id = response.json().get("id")
					if azure_id:
						_cache_azure_id_in_employee(email, azure_id)
					return azure_id
			except Exception as e:
				frappe.log_error(
					f"Failed to refresh token while fetching Azure ID for {email}: {str(e)}",
					"Teams Token Error",
				)

		elif response.status_code == 404:
			frappe.log_error(f"User not found in Azure AD: {email}", "Teams User Not Found")
		else:
			frappe.log_error(
				f"Failed to fetch Azure ID for {email}: {response.status_code} - {response.text}",
				"Teams API Error",
			)

		return None

	except requests.exceptions.Timeout:
		frappe.log_error(f"Timeout while fetching Azure ID for {email}", "Teams API Timeout")
		return None
	except requests.exceptions.RequestException as e:
		frappe.log_error(f"Network error fetching Azure ID for {email}: {str(e)}", "Teams Network Error")
		return None
	except Exception as e:
		frappe.log_error(f"Unexpected error fetching Azure ID for {email}: {str(e)}", "Teams API Error")
		return None


@frappe.whitelist()
def get_login_url(docname=None):
	"""Generate Microsoft OAuth login URL"""
	try:
		settings = get_settings()

		if not all([settings.client_id, settings.tenant_id, settings.redirect_uri]):
			frappe.throw(
				"Teams integration is not properly configured. Please check Client ID, Tenant ID, and Redirect URI."
			)

		scope = (
			"User.Read OnlineMeetings.ReadWrite offline_access Chat.ReadWrite "
			"Chat.Create Chat.ReadBasic User.ReadBasic.All ChannelMessage.Send Calendars.ReadWrite"
		)
		state = f"from_create_button::{docname}"
		login_url = (
			f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/authorize"
			f"?client_id={settings.client_id}&response_type=code"
			f"&redirect_uri={urllib.parse.quote(settings.redirect_uri, safe='')}"
			f"&response_mode=query&scope={urllib.parse.quote(scope)}&state={urllib.parse.quote(state)}"
		)
		return login_url

	except Exception as e:
		frappe.log_error(f"Failed to generate login URL: {str(e)}", "Teams Login URL Error")
		frappe.throw("Failed to generate authentication URL")


@frappe.whitelist()
def validate_settings():
	"""Validate Teams Settings configuration"""
	try:
		settings = get_settings()
		errors = []

		required_fields = {
			"client_id": "Client ID",
			"client_secret": "Client Secret",
			"tenant_id": "Tenant ID",
			"redirect_uri": "Redirect URI",
		}

		for field, label in required_fields.items():
			if not getattr(settings, field, None):
				errors.append(f"{label} is required")

		if settings.redirect_uri and not settings.redirect_uri.startswith(("http://", "https://")):
			errors.append("Redirect URI must start with http:// or https://")

		if settings.tenant_id:
			import re

			if not re.match(
				r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
				settings.tenant_id.lower(),
			):
				errors.append("Tenant ID should be a valid GUID format")

		return {"valid": len(errors) == 0, "errors": errors}

	except Exception as e:
		frappe.log_error(f"Settings validation error: {str(e)}", "Teams Settings Validation Error")
		return {"valid": False, "errors": ["Failed to validate settings"]}


@frappe.whitelist()
def test_api_connection():
	"""Test API connection with current tokens"""
	try:
		token = get_access_token()
		if not token:
			return {"success": False, "message": "No valid access token available"}

		response = requests.get(
			f"{GRAPH_API}/me", headers={"Authorization": f"Bearer {token}"}, timeout=10
		)

		if response.status_code == 200:
			user_data = response.json()
			return {
				"success": True,
				"message": "API connection successful",
				"user": {
					"name": user_data.get("displayName"),
					"email": user_data.get("mail") or user_data.get("userPrincipalName"),
				},
			}
		return {"success": False, "message": f"API connection failed: {response.status_code}"}

	except Exception as e:
		frappe.log_error(f"API connection test failed: {str(e)}", "Teams API Test Error")
		return {"success": False, "message": "API connection test failed"}
