# Copyright (c) 2026, siva@enfono.com
# Feature 1: Real-time Teams notifications via Microsoft Graph webhooks

import frappe
import requests
import json
from datetime import timedelta
from frappe.utils import now_datetime
from .helpers import get_access_token, GRAPH_API

# Graph allows max 60 min for chat message subscriptions
_CHAT_SUB_EXPIRY_MINUTES = 55
_CACHE_PREFIX = "ti_sub_"
_LAST_VISIT_PREFIX = "ti_last_visit_"


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def subscribe_chat_notifications(chat_id):
    """Create a Graph webhook subscription for new messages in a chat."""
    if not chat_id:
        frappe.throw("chat_id is required")

    token = get_access_token()
    if not token:
        return {"error": "auth_required"}

    notification_url = (
        f"{frappe.utils.get_url()}"
        "/api/method/teams_integration.api.realtime_notify.handle_chat_webhook"
    )
    expiry_str = (now_datetime() + timedelta(minutes=_CHAT_SUB_EXPIRY_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    payload = {
        "changeType": "created",
        "notificationUrl": notification_url,
        "resource": f"/chats/{chat_id}/messages",
        "expirationDateTime": expiry_str,
        "clientState": f"teams_integration_{chat_id[:20]}",
    }

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res = requests.post(f"{GRAPH_API}/subscriptions", headers=headers, json=payload, timeout=30)

    if res.status_code in (200, 201):
        sub_id = res.json().get("id")
        frappe.cache().set_value(
            f"{_CACHE_PREFIX}{chat_id}", sub_id, expires_in_sec=_CHAT_SUB_EXPIRY_MINUTES * 60
        )
        return {"success": True, "subscription_id": sub_id}

    frappe.log_error(
        f"Subscribe failed for {chat_id}: {res.status_code} - {res.text}",
        "Teams Realtime Subscribe Error",
    )
    return {"success": False, "error": res.text}


@frappe.whitelist()
def renew_all_chat_subscriptions():
    """Renew every live chat webhook subscription. Called hourly by the scheduler."""
    token = get_access_token()
    if not token:
        return {"renewed": 0}

    convs = frappe.get_all("Teams Conversation", fields=["name", "chat_id"])
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    renewed = 0

    for conv in convs:
        chat_id = conv.chat_id
        sub_id = frappe.cache().get_value(f"{_CACHE_PREFIX}{chat_id}")
        if not sub_id:
            # No active subscription — create one
            result = subscribe_chat_notifications(chat_id)
            if result.get("success"):
                renewed += 1
            continue

        expiry_str = (now_datetime() + timedelta(minutes=_CHAT_SUB_EXPIRY_MINUTES)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        try:
            res = requests.patch(
                f"{GRAPH_API}/subscriptions/{sub_id}",
                headers=headers,
                json={"expirationDateTime": expiry_str},
                timeout=10,
            )
            if res.status_code == 200:
                renewed += 1
            elif res.status_code == 404:
                # Expired — recreate
                frappe.cache().delete_value(f"{_CACHE_PREFIX}{chat_id}")
                result = subscribe_chat_notifications(chat_id)
                if result.get("success"):
                    renewed += 1
        except Exception as e:
            frappe.log_error(
                f"Renew failed for {chat_id}: {str(e)}", "Teams Subscription Renewal Error"
            )

    return {"renewed": renewed}


# ---------------------------------------------------------------------------
# Webhook endpoint (called by Microsoft Graph)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def handle_chat_webhook():
    """Receive Microsoft Graph chat-message webhook notifications."""
    # Graph validation handshake
    validation_token = frappe.request.args.get("validationToken")
    if validation_token:
        frappe.local.response["type"] = "json"
        frappe.local.response["http_status_code"] = 200
        frappe.local.response["message"] = validation_token
        return validation_token

    try:
        body = json.loads(frappe.request.data.decode("utf-8"))
        for notification in body.get("value", []):
            _process_notification(notification)
    except Exception as e:
        frappe.log_error(str(e), "Teams Chat Webhook Error")

    return {"status": "accepted"}


def _process_notification(notification):
    """Process one Graph notification, save the message locally, and publish realtime."""
    try:
        resource = notification.get("resource", "")
        parts = resource.strip("/").split("/")
        # Expected: chats/{chatId}/messages/{messageId}
        if len(parts) < 4 or parts[0] != "chats":
            return

        chat_id = parts[1]
        message_id = parts[3]

        token = get_access_token()
        if not token:
            return

        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(
            f"{GRAPH_API}/chats/{chat_id}/messages/{message_id}", headers=headers, timeout=10
        )
        if res.status_code != 200:
            return

        msg_data = res.json()
        sender_info = (msg_data.get("from") or {})
        user_info = (sender_info.get("user") or {})
        sender_name = user_info.get("displayName") or "Unknown"
        preview = ((msg_data.get("body") or {}).get("content") or "")[:120]

        from .chat import _save_message_local
        _save_message_local(msg_data, chat_id, None, None, "Inbound")

        conv = frappe.db.get_value(
            "Teams Conversation",
            {"chat_id": chat_id},
            ["document_type", "document_name"],
            as_dict=True,
        ) or {}

        frappe.publish_realtime(
            "teams_new_message",
            {
                "chat_id": chat_id,
                "sender": sender_name,
                "preview": preview,
                "document_type": conv.get("document_type"),
                "document_name": conv.get("document_name"),
            },
            after_commit=True,
        )
    except Exception as e:
        frappe.log_error(f"Notification processing error: {str(e)}", "Teams Realtime Error")


# ---------------------------------------------------------------------------
# Unread badge helpers (called from frontend)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_unread_count():
    """Return how many inbound Teams messages arrived since this user last visited the chat page."""
    try:
        last_visit = (
            frappe.cache().get_value(f"{_LAST_VISIT_PREFIX}{frappe.session.user}") or "1970-01-01"
        )
        count = frappe.db.count("Teams Chat Message", {"direction": "Inbound", "created_at": [">", last_visit]})
        return {"count": count}
    except Exception:
        return {"count": 0}


@frappe.whitelist()
def mark_visited():
    """Record the current user's visit to the Teams Chat page (resets the unread badge)."""
    frappe.cache().set_value(
        f"{_LAST_VISIT_PREFIX}{frappe.session.user}",
        now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
        expires_in_sec=7 * 24 * 3600,
    )
    return {"success": True}
