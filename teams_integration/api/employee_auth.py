# Copyright (c) 2026, siva@enfono.com

import frappe
import requests
import urllib.parse
from datetime import timedelta
from frappe.utils import now_datetime, get_datetime
from .helpers import get_settings, GRAPH_API


def _get_current_employee():
    """Return the Employee name for the currently logged-in user."""
    user = frappe.session.user
    if user == "Guest":
        return None
    email = frappe.db.get_value("User", user, "email")
    return (
        frappe.db.get_value("Employee", {"user_id": user}, "name")
        or frappe.db.get_value("Employee", {"company_email": email}, "name")
        or frappe.db.get_value("Employee", {"personal_email": email}, "name")
    )


@frappe.whitelist()
def get_employee_login_url():
    """Generate a per-employee OAuth URL. State encodes the current user's Employee name."""
    emp_name = _get_current_employee()
    if not emp_name:
        frappe.throw(
            "No Employee record is linked to your account. "
            "Ask HR to set your User ID on your Employee record."
        )

    settings = get_settings()
    if not all([settings.client_id, settings.tenant_id, settings.redirect_uri]):
        frappe.throw("Teams integration is not configured. Go to Teams Settings first.")

    scope = (
        "User.Read OnlineMeetings.ReadWrite offline_access "
        "Chat.ReadWrite Chat.Create Chat.ReadBasic User.ReadBasic.All Calendars.ReadWrite"
    )
    state = f"employee::{emp_name}"
    login_url = (
        f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/authorize"
        f"?client_id={settings.client_id}&response_type=code"
        f"&redirect_uri={urllib.parse.quote(settings.redirect_uri, safe='')}"
        f"&response_mode=query"
        f"&scope={urllib.parse.quote(scope)}"
        f"&state={urllib.parse.quote(state)}"
    )
    return {"login_url": login_url, "employee_name": emp_name}


def save_employee_tokens(employee_name, code, settings):
    """Exchange an authorization code for tokens and persist them on the Employee record."""
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
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        timeout=30,
    )

    if response.status_code != 200:
        frappe.log_error(
            f"Employee token exchange failed for {employee_name}: {response.status_code} - {response.text}",
            "Teams Employee OAuth Error",
        )
        frappe.throw("Authentication failed. Please try again.")

    token_data = response.json()
    expires_in = token_data.get("expires_in", 3600)

    # Try to backfill azure_object_id using the personal token
    azure_id = None
    try:
        me_resp = requests.get(
            f"{GRAPH_API}/me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
            timeout=10,
        )
        if me_resp.status_code == 200:
            azure_id = me_resp.json().get("id")
    except Exception:
        pass

    updates = {
        "custom_employee_access_token": token_data.get("access_token"),
        "custom_employee_token_expiry": now_datetime() + timedelta(seconds=expires_in - 300),
    }
    if token_data.get("refresh_token"):
        updates["custom_employee_refresh_token"] = token_data["refresh_token"]
    if azure_id and not frappe.db.get_value("Employee", employee_name, "azure_object_id"):
        updates["azure_object_id"] = azure_id

    for field, value in updates.items():
        frappe.db.set_value("Employee", employee_name, field, value)
    frappe.db.commit()


def get_employee_token(employee_name):
    """Return a valid personal access token for an employee, refreshing if near expiry."""
    row = frappe.db.get_value(
        "Employee",
        employee_name,
        ["custom_employee_access_token", "custom_employee_refresh_token", "custom_employee_token_expiry"],
        as_dict=True,
    )
    if not row or not row.custom_employee_access_token:
        return None

    if row.custom_employee_token_expiry:
        expiry = get_datetime(row.custom_employee_token_expiry)
        if (expiry - now_datetime()).total_seconds() < 300:
            return _refresh_employee_token(employee_name, row.custom_employee_refresh_token)

    return row.custom_employee_access_token


def _refresh_employee_token(employee_name, refresh_token):
    """Silently refresh the personal token for an employee."""
    if not refresh_token:
        return None
    try:
        settings = get_settings()
        token_url = f"https://login.microsoftonline.com/{settings.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "https://graph.microsoft.com/.default",
        }
        resp = requests.post(token_url, data=data, timeout=30)
        if resp.status_code == 200:
            td = resp.json()
            expires_in = td.get("expires_in", 3600)
            updates = {
                "custom_employee_access_token": td.get("access_token"),
                "custom_employee_token_expiry": now_datetime() + timedelta(seconds=expires_in - 300),
            }
            if td.get("refresh_token"):
                updates["custom_employee_refresh_token"] = td["refresh_token"]
            for field, value in updates.items():
                frappe.db.set_value("Employee", employee_name, field, value)
            frappe.db.commit()
            return td.get("access_token")
    except Exception as e:
        frappe.log_error(
            f"Employee token refresh failed for {employee_name}: {str(e)}",
            "Teams Employee Token Error",
        )
    return None


@frappe.whitelist()
def get_my_auth_status():
    """Return Teams personal auth status for the current user's Employee."""
    emp_name = _get_current_employee()
    if not emp_name:
        return {"authenticated": False, "reason": "no_employee"}

    token = frappe.db.get_value("Employee", emp_name, "custom_employee_access_token")
    return {"authenticated": bool(token), "employee_name": emp_name}


@frappe.whitelist()
def disconnect_my_teams():
    """Remove the current user's personal Teams tokens."""
    emp_name = _get_current_employee()
    if not emp_name:
        frappe.throw("No Employee record found for your account.")

    for field in ("custom_employee_access_token", "custom_employee_refresh_token", "custom_employee_token_expiry"):
        frappe.db.set_value("Employee", emp_name, field, None)
    frappe.db.commit()
    return {"success": True}
