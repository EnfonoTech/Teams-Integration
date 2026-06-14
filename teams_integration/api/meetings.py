# Copyright (c) 2026, siva@enfono.com

import json
from datetime import datetime, time, timedelta
import frappe
import pytz
import requests
from frappe.utils import get_datetime, now_datetime
from .helpers import get_access_token, get_azure_user_id_by_email, get_login_url

GRAPH_API = "https://graph.microsoft.com/v1.0"

SUPPORTED_DOCTYPES = {
	"Event": {
		"participants_field": "event_participants",
		"email_field": "email",
		"subject_field": "subject",
		"start_field": "starts_on",
		"end_field": "ends_on",
	},
	"Project": {
		"participants_field": "users",
		"email_field": "email",
		"subject_field": "project_name",
		"start_field": "expected_start_date",
		"end_field": "expected_end_date",
	},
	"Interview": {
		"participants_field": ["interview_details", "custom_applicant_email"],
		"email_field": "interviewer",
		"subject_field": "name",
		"start_date": "scheduled_on",
		"start_field": "from_time",
		"end_field": "to_time",
	},
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _safe_str(obj) -> str:
	try:
		return json.dumps(obj, default=str, ensure_ascii=False) if isinstance(obj, (dict, list)) else str(obj)
	except Exception:
		return "<unprintable>"


def safe_log_error(message: str, title: str = "Teams Integration Error"):
	try:
		frappe.log_error(message=_safe_str(message), title=_safe_str(title)[:140])
	except Exception:
		pass


def to_utc_isoformat(dt, timezone_str="Asia/Kolkata"):
	try:
		if not dt:
			raise ValueError("no datetime provided")
		if not isinstance(dt, datetime):
			dt = get_datetime(dt)
		try:
			local_tz = pytz.timezone(timezone_str)
		except Exception:
			local_tz = pytz.utc
		if dt.tzinfo is None:
			dt = local_tz.localize(dt)
		return dt.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
	except Exception as e:
		safe_log_error(f"to_utc_isoformat failed: {e}\nvalue={dt}")
		return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_datetime_with_time(value, default_hour=9, default_minute=0):
	try:
		if not value:
			return None
		dt = value if isinstance(value, datetime) else get_datetime(value)
		if dt.time() == time(0, 0, 0):
			dt = dt.replace(hour=default_hour, minute=default_minute)
		return dt
	except Exception as e:
		safe_log_error(f"ensure_datetime_with_time failed: {e}\nvalue={value}")
		return None


def _headers_with_auth(token: str, json_content=True):
	h = {"Authorization": f"Bearer {token}"}
	if json_content:
		h["Content-Type"] = "application/json"
	return h


def _check_api_response(res, docname=None):
	if res.status_code == 401:
		return {"error": "auth_required", "login_url": get_login_url(docname) if docname else None}
	if res.status_code == 403:
		frappe.throw(
			"<b>Permission Denied (403)</b><br>"
			"Your Microsoft Token lacks Calendars.ReadWrite permission.<br>"
			"Go to Teams Settings and click 'Authenticate with Teams' again."
		)
	return None


# ---------------------------------------------------------------------------
# Attendee & Email Helpers
# ---------------------------------------------------------------------------

def _collect_participant_emails(doc):
	"""Collect participant emails from the document's configured field(s)."""
	doctype = doc.doctype
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(f"Doctype {doctype} is not supported for Teams meetings.")

	cfg = SUPPORTED_DOCTYPES[doctype]
	participants_fields = cfg["participants_field"]
	email_field = cfg["email_field"]

	if isinstance(participants_fields, str):
		participants_fields = [participants_fields]

	emails = set()

	for field in participants_fields:
		field_value = getattr(doc, field, None)

		if isinstance(field_value, list):
			for row in field_value:
				email = None
				user_link = getattr(row, "user", None)
				if user_link:
					email = frappe.db.get_value("User", user_link, "email")
				if not email:
					email = getattr(row, email_field, None)
				if email:
					emails.add(email.lower())

		elif isinstance(field_value, str) and "@" in field_value:
			emails.add(field_value.lower())

	return list(emails)


def _build_event_attendees(emails):
	return [{"emailAddress": {"address": e}, "type": "required"} for e in emails if e]


def _build_attendees_from_participants_list(emails):
	attendees = []
	for email in emails:
		azure_id = get_azure_user_id_by_email(email)
		if azure_id:
			attendees.append({"identity": {"user": {"id": azure_id}}})
	return attendees


def _build_default_times_for_doctype(doc, doctype: str):
	cfg = SUPPORTED_DOCTYPES.get(doctype) or {}
	start_field = cfg.get("start_field")
	end_field = cfg.get("end_field")
	start_date_field = cfg.get("start_date")

	if start_date_field:
		base_date = getattr(doc, start_date_field, None)
		start_time = getattr(doc, start_field, None) or "09:00:00"
		end_time = getattr(doc, end_field, None) or "09:30:00"
		start_val = f"{base_date} {start_time}" if base_date else None
		end_val = f"{base_date} {end_time}" if base_date else None
	else:
		start_val = getattr(doc, start_field, None) if start_field else None
		end_val = getattr(doc, end_field, None) if end_field else None

	if doctype == "Project":
		start_dt = ensure_datetime_with_time(start_val, 9, 0)
		end_dt = ensure_datetime_with_time(end_val, 17, 30)
	else:
		start_dt = ensure_datetime_with_time(start_val)
		end_dt = ensure_datetime_with_time(end_val)

	if not start_dt:
		start_dt = now_datetime()
	if not end_dt or end_dt <= start_dt:
		end_dt = start_dt + timedelta(hours=1)
	return start_dt, end_dt


def _resolve_subject(doc, doctype: str, docname: str) -> str:
	cfg = SUPPORTED_DOCTYPES.get(doctype) or {}
	subject_field = cfg.get("subject_field")
	subject = (getattr(doc, subject_field, None) or "").strip() if subject_field else ""
	return subject or f"{doctype} Meeting: {docname}"


@frappe.whitelist()
def _extract_meeting_id_from_join_url(join_url: str, token: str):
	try:
		if not join_url:
			return None
		search_url = f"{GRAPH_API}/me/onlineMeetings?$filter=JoinWebUrl eq '{join_url}'"
		res = requests.get(search_url, headers=_headers_with_auth(token, json_content=False), timeout=30)
		if res.status_code == 200:
			meetings = res.json().get("value", [])
			if meetings:
				return meetings[0].get("id")
		return None
	except Exception:
		return None


# ---------------------------------------------------------------------------
# API: Create or Update meeting
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_meeting(docname, doctype):
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(f"Doctype {doctype} is not supported.")

	try:
		token = get_access_token()
		if not token:
			return {"error": "auth_required", "login_url": get_login_url(docname)}

		doc = frappe.get_doc(doctype, docname)
		participant_emails = _collect_participant_emails(doc)

		existing_meeting_url = doc.get("custom_teams_meeting_url")
		if existing_meeting_url:
			existing_event_id = doc.get("custom_outlook_event_id")
			if existing_event_id:
				return _update_event_attendees(existing_event_id, participant_emails, token)
			return _update_existing_meeting(doc, participant_emails, existing_meeting_url, token)

		return _create_new_meeting(doc, doctype, docname, participant_emails, token)

	except frappe.ValidationError:
		raise
	except Exception as e:
		safe_log_error(f"Create error: {e}", "Teams Meeting Create Error")
		frappe.throw("Failed to create Teams meeting.")


def _create_new_meeting(doc, doctype, docname, participant_emails, token):
	try:
		subject = _resolve_subject(doc, doctype, docname)
		start_dt, end_dt = _build_default_times_for_doctype(doc, doctype)

		payload = {
			"subject": subject,
			"start": {"dateTime": to_utc_isoformat(start_dt), "timeZone": "UTC"},
			"end": {"dateTime": to_utc_isoformat(end_dt), "timeZone": "UTC"},
			"isOnlineMeeting": True,
			"onlineMeetingProvider": "teamsForBusiness",
			"attendees": _build_event_attendees(participant_emails),
		}

		res = requests.post(
			f"{GRAPH_API}/me/events", headers=_headers_with_auth(token), json=payload, timeout=30
		)

		check = _check_api_response(res, docname)
		if check:
			return check

		if res.status_code not in (200, 201):
			frappe.throw(f"Teams API error {res.status_code} - {res.text}")

		data = res.json() or {}
		join_url = data.get("onlineMeeting", {}).get("joinUrl") or data.get("webLink")

		if not join_url:
			frappe.throw("Event created but no Teams link returned.")

		if frappe.db.has_column(doctype, "custom_outlook_event_id"):
			doc.db_set("custom_outlook_event_id", data.get("id"))

		doc.db_set("custom_teams_meeting_url", join_url)
		frappe.db.commit()

		return {
			"success": True,
			"message": "Outlook Calendar blocked and Teams meeting created.",
			"meeting_url": join_url,
		}
	except frappe.ValidationError:
		raise
	except Exception as e:
		safe_log_error(f"Error creating event: {e}", "Event Creation Error")
		frappe.throw(str(e))


def _update_existing_meeting(doc, participant_emails, meeting_url, token):
	try:
		meeting_id = _extract_meeting_id_from_join_url(meeting_url, token)
		if meeting_id:
			return _update_onlinemeeting_attendees(meeting_id, participant_emails, token)
		return {"error": "not_found", "message": "Could not find meeting on Teams/Outlook."}
	except Exception as e:
		safe_log_error(f"Update error: {e}", "Meeting Update Error")
		frappe.throw("Failed to update meeting.")


def _update_event_attendees(event_id, participant_emails, token):
	headers = _headers_with_auth(token)
	get_res = requests.get(f"{GRAPH_API}/me/events/{event_id}", headers=headers)
	check = _check_api_response(get_res)
	if check:
		return check
	if get_res.status_code != 200:
		frappe.throw("Failed to fetch existing event.")

	current_data = get_res.json()
	existing_emails = {
		a.get("emailAddress", {}).get("address", "").lower()
		for a in current_data.get("attendees", [])
	}

	new_attendees = list(current_data.get("attendees", []))
	for email in participant_emails:
		if email and email.lower() not in existing_emails:
			new_attendees.append({"emailAddress": {"address": email}, "type": "required"})

	if len(new_attendees) == len(current_data.get("attendees", [])):
		return {"success": True, "message": "No new participants to add."}

	patch_res = requests.patch(
		f"{GRAPH_API}/me/events/{event_id}", headers=headers, json={"attendees": new_attendees}
	)
	check = _check_api_response(patch_res)
	if check:
		return check
	if patch_res.status_code == 200:
		return {"success": True, "message": "Outlook Event attendees updated."}
	frappe.throw("Failed to update Outlook Event.")


def _update_onlinemeeting_attendees(meeting_id, participant_emails, token):
	attendees = _build_attendees_from_participants_list(participant_emails)
	patch_res = requests.patch(
		f"{GRAPH_API}/me/onlineMeetings/{meeting_id}",
		headers=_headers_with_auth(token),
		json={"participants": {"attendees": attendees}},
	)
	if patch_res.status_code in (200, 204):
		return {"success": True, "message": "Teams Meeting participants updated."}
	frappe.throw("Failed to update Teams Meeting.")


# ---------------------------------------------------------------------------
# API: Details
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_meeting_details(docname, doctype):
	try:
		doc = frappe.get_doc(doctype, docname)
		url = doc.get("custom_teams_meeting_url")
		if not url:
			return {"exists": False, "message": "No meeting found."}

		token = get_access_token()
		if not token:
			return {"exists": True, "url": url, "message": "Auth required."}

		event_id = doc.get("custom_outlook_event_id")
		if event_id:
			res = requests.get(f"{GRAPH_API}/me/events/{event_id}", headers=_headers_with_auth(token))
			if res.status_code == 200:
				d = res.json()
				return {
					"exists": True,
					"url": url,
					"details": {
						"subject": d.get("subject"),
						"startDateTime": d.get("start", {}).get("dateTime"),
						"endDateTime": d.get("end", {}).get("dateTime"),
						"participants": len(d.get("attendees", [])),
						"type": "Outlook Event",
					},
				}

		meeting_id = _extract_meeting_id_from_join_url(url, token)
		if meeting_id:
			res = requests.get(f"{GRAPH_API}/me/onlineMeetings/{meeting_id}", headers=_headers_with_auth(token))
			if res.status_code == 200:
				d = res.json()
				return {
					"exists": True,
					"url": url,
					"details": {
						"subject": d.get("subject"),
						"startDateTime": d.get("startDateTime"),
						"endDateTime": d.get("endDateTime"),
						"participants": len(d.get("participants", {}).get("attendees", [])),
						"type": "Teams Meeting",
					},
				}

		return {"exists": True, "url": url, "message": "Details unavailable."}
	except Exception as e:
		safe_log_error(f"Details error: {e}", "Details Error")
		return {"exists": False, "message": "Error fetching details."}


# ---------------------------------------------------------------------------
# API: Delete
# ---------------------------------------------------------------------------

@frappe.whitelist()
def delete_meeting(docname, doctype):
	try:
		doc = frappe.get_doc(doctype, docname)
		url = doc.get("custom_teams_meeting_url")
		if not url:
			return {"success": True}

		token = get_access_token()
		if not token:
			return {"error": "auth_required"}

		event_id = doc.get("custom_outlook_event_id")
		if event_id:
			requests.delete(f"{GRAPH_API}/me/events/{event_id}", headers=_headers_with_auth(token))
			doc.db_set("custom_teams_meeting_url", "")
			return {"success": True, "message": "Outlook Event deleted."}

		meeting_id = _extract_meeting_id_from_join_url(url, token)
		if meeting_id:
			requests.delete(f"{GRAPH_API}/me/onlineMeetings/{meeting_id}", headers=_headers_with_auth(token))
			doc.db_set("custom_teams_meeting_url", "")
			return {"success": True, "message": "Teams Meeting deleted."}

		doc.db_set("custom_teams_meeting_url", "")
		return {"success": True, "message": "URL cleared (not found on remote)."}

	except Exception as e:
		safe_log_error(f"Delete error: {e}", "Delete Error")
		return {"success": False, "message": "Error deleting meeting."}


# ---------------------------------------------------------------------------
# API: Reschedule
# ---------------------------------------------------------------------------

@frappe.whitelist()
def reschedule_meeting(docname, doctype, new_start_time=None, new_end_time=None):
	try:
		doc = frappe.get_doc(doctype, docname)
		url = doc.get("custom_teams_meeting_url")
		if not url:
			frappe.throw("No meeting found.")

		token = get_access_token()
		if not token:
			return {"error": "auth_required", "login_url": get_login_url(docname)}

		if not new_start_time or not new_end_time:
			start_dt, end_dt = _build_default_times_for_doctype(doc, doctype)
		else:
			if doctype == "Project":
				start_dt = ensure_datetime_with_time(new_start_time, 9, 0)
				end_dt = ensure_datetime_with_time(new_end_time, 17, 30)
			else:
				start_dt = ensure_datetime_with_time(new_start_time)
				end_dt = ensure_datetime_with_time(new_end_time)

		if start_dt >= end_dt:
			end_dt = start_dt + timedelta(hours=1)

		start_iso = to_utc_isoformat(start_dt)
		end_iso = to_utc_isoformat(end_dt)

		event_id = doc.get("custom_outlook_event_id")
		if event_id:
			payload = {
				"start": {"dateTime": start_iso, "timeZone": "UTC"},
				"end": {"dateTime": end_iso, "timeZone": "UTC"},
			}
			res = requests.patch(
				f"{GRAPH_API}/me/events/{event_id}", headers=_headers_with_auth(token), json=payload
			)
			check = _check_api_response(res)
			if check:
				return check
			if res.status_code == 200:
				return {"success": True, "message": "Outlook Calendar updated."}
			frappe.throw(f"Outlook update failed: {res.status_code}")

		meeting_id = _extract_meeting_id_from_join_url(url, token)
		if meeting_id:
			res = requests.patch(
				f"{GRAPH_API}/me/onlineMeetings/{meeting_id}",
				headers=_headers_with_auth(token),
				json={"startDateTime": start_iso, "endDateTime": end_iso},
			)
			if res.status_code in (200, 204):
				return {"success": True, "message": "Teams Meeting updated."}

		frappe.throw("Could not update meeting (ID not found).")

	except frappe.ValidationError:
		raise
	except Exception as e:
		safe_log_error(f"Reschedule error: {e}", "Reschedule Error")
		frappe.throw("Failed to reschedule.")


# ---------------------------------------------------------------------------
# API: Attendees
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_meeting_attendees(docname, doctype):
	try:
		doc = frappe.get_doc(doctype, docname)
		url = doc.get("custom_teams_meeting_url")
		if not url:
			return {"attendees": [], "message": "No meeting found."}

		token = get_access_token()
		if not token:
			return {"attendees": [], "message": "Auth required."}

		attendees = []
		event_id = doc.get("custom_outlook_event_id")
		if event_id:
			res = requests.get(f"{GRAPH_API}/me/events/{event_id}", headers=_headers_with_auth(token))
			if res.status_code == 200:
				for a in res.json().get("attendees", []):
					attendees.append({
						"email": a.get("emailAddress", {}).get("address"),
						"displayName": a.get("emailAddress", {}).get("name") or "Unknown",
					})
				return {"attendees": attendees, "count": len(attendees), "type": "Outlook Event"}

		meeting_id = _extract_meeting_id_from_join_url(url, token)
		if meeting_id:
			res = requests.get(f"{GRAPH_API}/me/onlineMeetings/{meeting_id}", headers=_headers_with_auth(token))
			if res.status_code == 200:
				for a in res.json().get("participants", {}).get("attendees", []):
					user = a.get("identity", {}).get("user", {})
					attendees.append({
						"id": user.get("id"),
						"displayName": user.get("displayName"),
						"email": user.get("email"),
					})
				return {"attendees": attendees, "count": len(attendees), "type": "Teams Meeting"}

		return {"attendees": [], "message": "Details unavailable."}
	except Exception as e:
		safe_log_error(f"Attendees error: {e}", "Attendees Error")
		return {"attendees": [], "message": "Error fetching attendees."}


@frappe.whitelist()
def add_external_attendees(docname, doctype, external_emails):
	"""
	Feature 7: Add external / guest attendees (non-tenant emails) to an existing Outlook event.
	external_emails: comma-separated string of email addresses.
	"""
	if not external_emails:
		frappe.throw("At least one external email is required.")

	emails = [e.strip().lower() for e in str(external_emails).split(",") if "@" in e.strip()]
	if not emails:
		frappe.throw("No valid email addresses provided.")

	doc = frappe.get_doc(doctype, docname)
	event_id = doc.get("custom_outlook_event_id")
	if not event_id:
		frappe.throw("No Outlook Event is linked to this document. Create a Teams Meeting first.")

	token = get_access_token()
	if not token:
		return {"error": "auth_required"}

	headers = _headers_with_auth(token)

	# Fetch existing attendees
	get_res = requests.get(f"{GRAPH_API}/me/events/{event_id}", headers=headers, timeout=30)
	check = _check_api_response(get_res, docname)
	if check:
		return check
	if get_res.status_code != 200:
		frappe.throw("Could not fetch the existing Outlook event.")

	current = get_res.json()
	existing_emails = {
		a.get("emailAddress", {}).get("address", "").lower()
		for a in current.get("attendees", [])
	}

	new_attendees = list(current.get("attendees", []))
	added = 0
	for email in emails:
		if email not in existing_emails:
			new_attendees.append({"emailAddress": {"address": email}, "type": "required"})
			added += 1

	if added == 0:
		return {"success": True, "message": "All specified emails are already attendees."}

	patch_res = requests.patch(
		f"{GRAPH_API}/me/events/{event_id}",
		headers=headers,
		json={"attendees": new_attendees},
		timeout=30,
	)
	check = _check_api_response(patch_res, docname)
	if check:
		return check
	if patch_res.status_code == 200:
		# Also persist the email list on the doc for reference
		if frappe.db.has_column(doctype, "custom_external_attendees"):
			all_external = doc.get("custom_external_attendees") or ""
			existing_set = {e.strip() for e in all_external.split(",") if e.strip()}
			existing_set.update(emails)
			doc.db_set("custom_external_attendees", ", ".join(sorted(existing_set)))
		frappe.db.commit()
		return {"success": True, "message": f"Added {added} external attendee(s) to the meeting."}

	frappe.throw(f"Failed to update Outlook Event attendees: {patch_res.status_code}")


@frappe.whitelist()
def fetch_meeting_recordings(docname, doctype):
	"""
	Feature 5: Fetch recording links for a completed Teams meeting.

	Requires the OnlineMeetingRecording.Read.All delegated permission on the Azure app.
	Saves the first recording URL to custom_recording_url on the document.
	"""
	doc = frappe.get_doc(doctype, docname)
	join_url = doc.get("custom_teams_meeting_url")
	if not join_url:
		return {"recordings": [], "message": "No meeting URL found."}

	token = get_access_token()
	if not token:
		return {"error": "auth_required"}

	headers = _headers_with_auth(token, json_content=False)
	meeting_id = _extract_meeting_id_from_join_url(join_url, token)
	if not meeting_id:
		return {"recordings": [], "message": "Could not resolve meeting ID."}

	try:
		res = requests.get(
			f"{GRAPH_API}/me/onlineMeetings/{meeting_id}/recordings",
			headers=headers,
			timeout=30,
		)
	except requests.exceptions.Timeout:
		frappe.throw("Request timed out while fetching recordings.")

	if res.status_code == 403:
		return {
			"recordings": [],
			"message": "OnlineMeetingRecording.Read.All permission is required. Add it in Azure App Registration.",
		}
	if res.status_code != 200:
		frappe.log_error(
			f"Recording fetch failed {res.status_code}: {res.text}", "Teams Recording Fetch Error"
		)
		return {"recordings": [], "message": f"API error {res.status_code}"}

	recordings = []
	for rec in res.json().get("value", []):
		recordings.append({
			"id": rec.get("id"),
			"createdDateTime": rec.get("createdDateTime"),
			"recordingContentUrl": rec.get("recordingContentUrl"),
		})

	# Save the first recording URL on the document
	if recordings and frappe.db.has_column(doctype, "custom_recording_url"):
		doc.db_set("custom_recording_url", recordings[0].get("recordingContentUrl") or "")
		frappe.db.commit()

	return {"recordings": recordings, "count": len(recordings)}


@frappe.whitelist()
def fetch_meeting_transcript(docname, doctype):
	"""
	Feature 5: Fetch transcript for a completed Teams meeting.

	Requires OnlineMeetingTranscript.Read.All delegated permission.
	Saves the transcript download URL to custom_transcript_url on the document.
	"""
	doc = frappe.get_doc(doctype, docname)
	join_url = doc.get("custom_teams_meeting_url")
	if not join_url:
		return {"transcripts": [], "message": "No meeting URL found."}

	token = get_access_token()
	if not token:
		return {"error": "auth_required"}

	headers = _headers_with_auth(token, json_content=False)
	meeting_id = _extract_meeting_id_from_join_url(join_url, token)
	if not meeting_id:
		return {"transcripts": [], "message": "Could not resolve meeting ID."}

	try:
		res = requests.get(
			f"{GRAPH_API}/me/onlineMeetings/{meeting_id}/transcripts",
			headers=headers,
			timeout=30,
		)
	except requests.exceptions.Timeout:
		frappe.throw("Request timed out while fetching transcripts.")

	if res.status_code == 403:
		return {
			"transcripts": [],
			"message": "OnlineMeetingTranscript.Read.All permission is required. Add it in Azure App Registration.",
		}
	if res.status_code != 200:
		frappe.log_error(
			f"Transcript fetch failed {res.status_code}: {res.text}", "Teams Transcript Fetch Error"
		)
		return {"transcripts": [], "message": f"API error {res.status_code}"}

	transcripts = []
	for tr in res.json().get("value", []):
		transcripts.append({
			"id": tr.get("id"),
			"createdDateTime": tr.get("createdDateTime"),
			"transcriptContentUrl": tr.get("transcriptContentUrl"),
		})

	if transcripts and frappe.db.has_column(doctype, "custom_transcript_url"):
		doc.db_set("custom_transcript_url", transcripts[0].get("transcriptContentUrl") or "")
		frappe.db.commit()

	return {"transcripts": transcripts, "count": len(transcripts)}


@frappe.whitelist()
def validate_meeting_time(start_time, end_time, timezone_str="Asia/Kolkata"):
	try:
		start_dt = get_datetime(start_time)
		end_dt = get_datetime(end_time)
		errors = []
		if start_dt >= end_dt:
			errors.append("End time must be after start time.")
		duration = end_dt - start_dt
		if duration.total_seconds() > 24 * 3600:
			errors.append("Meeting duration cannot exceed 24 hours.")
		if duration.total_seconds() < 15 * 60:
			errors.append("Meeting duration should be at least 15 minutes.")
		if start_dt < now_datetime():
			errors.append("Meeting cannot be scheduled in the past.")
		return {
			"valid": len(errors) == 0,
			"errors": errors,
			"duration_hours": round(duration.total_seconds() / 3600, 2),
		}
	except Exception as e:
		return {"valid": False, "errors": [f"Invalid date/time format: {e}"]}
