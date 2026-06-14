# Teams Integration — Features Guide

**App:** `teams_integration`  
**Author:** siva@enfono.com

This document covers every advanced feature in the app: what it does, how to use it, additional Azure permissions required, and how to verify it is working.

---

## Table of Contents

1. [Real-time Notifications](#feature-1--real-time-notifications)
2. [Adaptive Cards](#feature-2--adaptive-cards)
3. [Teams Presence Status](#feature-3--teams-presence-status)
4. [Workflow State → Teams Notification](#feature-4--workflow-state--teams-notification)
5. [Meeting Transcripts & Recordings](#feature-5--meeting-transcripts--recordings)
6. [Two-way Calendar Sync](#feature-6--two-way-calendar-sync)
7. [External Guest Meeting Invite](#feature-7--external-guest-meeting-invite)
8. [Teams Activity Report](#feature-8--teams-activity-report)

---

## Feature 1 — Real-time Notifications

### What it does

When someone sends a message in a Teams chat that is linked to an ERPNext document, a real-time browser notification appears inside ERPNext — the Teams Chat page auto-refreshes and a toast alert shows the sender's name.  
If you are viewing a *different* conversation, the conversation row in the sidebar is bolded so you know it has a new message.

### How it works

- When a group chat is created for a document, the app subscribes to a Microsoft Graph webhook for that chat's messages.  
- Microsoft Graph posts a notification to `<site>/api/method/teams_integration.api.realtime_notify.handle_chat_webhook`.  
- ERPNext processes it, saves the message locally, and calls `frappe.publish_realtime("teams_new_message", ...)`.  
- The Teams Chat page listens for `teams_new_message` and refreshes.

### Subscription lifecycle

Graph chat-message subscriptions expire after **60 minutes**. The hourly scheduler task `renew_all_chat_subscriptions` extends them automatically. If a subscription is not found (e.g. after a downtime), it is recreated on the next hourly run.

### Unread badge

`get_unread_count()` returns how many inbound messages arrived since you last opened the Teams Chat page. `mark_visited()` resets this counter and is called automatically when the page loads.

### Additional Azure permissions

None beyond what is already configured. The webhook uses the same admin token.

> **Requirement:** Your ERPNext site must be publicly accessible over HTTPS. Local/ngrok setups must expose the correct URL.

### Testing

1. Open the Teams Chat page (`/app/teams-chat`) in ERPNext.
2. From **Microsoft Teams**, send a message into a group chat that is linked to a Project or Event.
3. Within seconds, the Teams Chat page should refresh and show the new message without a manual sync.
4. If you are not on the chat page, a blue toast alert should appear: *"New Teams message from [Sender]"*.
5. Navigate away, wait 1+ hour, then check: **Settings → Error Log** should contain a `Teams Subscription Renewal Daily` entry with `"renewed": N`.

---

## Feature 2 — Adaptive Cards

### What it does

Instead of plain-text messages, the app can send **rich interactive cards** to Teams chats. Cards display structured information (facts, titles, colours) and have clickable buttons that open the linked ERPNext document directly in the browser.

### Available cards

| Card | Trigger | Button |
|---|---|---|
| **Approval Request** | "Send Approval Card" on Event/Project form | "Open & Approve" → opens the ERPNext document |
| **Meeting Invite** | "Share Meeting Card" on Event/Project form | "Join Teams Meeting" + "View Document" |
| **Task Assignment** | API call: `send_task_card` | "View Task" |
| **Status Update** | Automatically sent by Feature 4 on workflow change | "Open Document" |

### How to use (from the form)

1. Open an **Event** or **Project** that has a Teams chat linked (`custom_teams_chat_id` is set).
2. Click **Teams → Send Approval Card** (or **Share Meeting Card**).
3. The card appears in the linked Teams group chat.

### API usage

```python
# From server-side Python or bench console:
frappe.call("teams_integration.api.adaptive_cards.send_approval_card",
    chat_id="...", doctype="Project", docname="PROJ-0001", note="Please review")

frappe.call("teams_integration.api.adaptive_cards.send_task_card",
    chat_id="...", task_name="TASK-0042", assigned_to_email="ahmed@company.com",
    due_date="2026-07-01")
```

### Limitations

- Action buttons use `Action.OpenUrl` — they open the ERPNext URL in a browser, not inside Teams.  
- Inline approve/reject *within* Teams (without opening a browser) requires a Microsoft Bot Framework integration, which is a separate, more complex setup.

### Additional Azure permissions

None.

### Testing

1. Open a **Project** that has a Teams group chat linked.
2. Click **Teams → Send Approval Card**, add an optional note, click **Send**.
3. Open Microsoft Teams and find the project's group chat.
4. Verify the card appears with the document name, your name as requester, and an **Open & Approve** button.
5. Click the button — it should open the ERPNext Project form in a new browser tab.

---

## Feature 3 — Teams Presence Status

### What it does

Shows a live Teams presence badge on the Employee form — **Available** (green), **Busy** (red), **Away** (yellow), or **Offline** (grey) — fetched from Microsoft Graph's Presence API.

### Where it appears

On the Employee form dashboard, below the "Teams Linked" indicator:  
`Teams: Available` / `Teams: Busy` / etc.

### Additional Azure permission required

You must add **`Presence.Read.All`** (delegated) to your Azure app's API permissions and re-grant admin consent.

> **Steps:**  
> Azure Portal → App Registration → API permissions → Add a permission → Microsoft Graph → Delegated → `Presence.Read.All` → Grant admin consent.  
> Then go to **Teams Settings → Authenticate with Teams** and re-authenticate.

If the permission is missing, the badge shows `Teams: Presence.Read.All permission required` in grey — this is not an error, just a missing permission notice.

### Testing

1. Open any **Employee** record that has a synced Azure Object ID.
2. The dashboard should show a colour-coded presence badge.
3. In Microsoft Teams, change your status to **Do Not Disturb**, wait 30 seconds, then reload the Employee form.
4. The badge should reflect the new status.

---

## Feature 4 — Workflow State → Teams Notification

### What it does

Whenever an ERPNext document with a linked Teams chat has its **workflow state changed**, the app automatically:

1. Sends a plain-text notification to the linked group chat: *"Project [PROJ-0001] status changed from Draft → Approved by Siva"*
2. Follows it with a **Status Update Adaptive Card** (Feature 2) showing the change details and a link to the document.

### How it works

- `before_save` hook stores the old workflow state.
- `on_update` hook compares old vs. new state. If different and a Teams chat is linked, both a plain message and a card are sent.
- No manual action required — it fires on every save where the workflow state changes.

### Use case example

1. A Purchase Order goes through a multi-step workflow: **Draft → Pending Approval → Approved → Rejected**.
2. Each state transition sends a notification to the Purchase Order's linked Teams chat so the whole team sees who approved or rejected it and when.

### Limitations

- Only fires when `custom_teams_chat_id` is set on the document (i.e., after "Create Teams Chat" has been clicked).
- Does not fire for documents without a workflow.

### Testing

1. Set up an ERPNext workflow on **Project** or **Event** with at least 2 states (e.g., *Open* → *In Review*).
2. Open a document that has a linked Teams chat.
3. Change the workflow state by clicking the workflow action button and saving.
4. In Microsoft Teams, the group chat should receive:
   - A plain-text message announcing the state change.
   - A Status Update Adaptive Card with an "Open Document" button.

---

## Feature 5 — Meeting Transcripts & Recordings

### What it does

After a Teams meeting has ended, you can fetch:

- **Recording URL** — direct link to the MP4 recording of the meeting, saved to `custom_recording_url` on the document.
- **Transcript URL** — link to the VTT/text transcript, saved to `custom_transcript_url` on the document.

Buttons are available on **Event** and **Project** forms whenever a Teams meeting URL is set.

### Additional Azure permissions required

| Permission | Purpose |
|---|---|
| `OnlineMeetingRecording.Read.All` | Read meeting recordings |
| `OnlineMeetingTranscript.Read.All` | Read meeting transcripts |

Both are **delegated** permissions. Add them in Azure Portal and re-authenticate in Teams Settings.

> **Note:** Recordings are only available after the meeting has ended AND Teams has finished processing the recording (usually 10–30 minutes after the meeting). Clicking "Fetch Recording" before then returns an empty list.

### Testing

1. Create a Teams meeting from an **Event** form (**Teams → Create Teams Meeting**) and hold the meeting in Microsoft Teams.
2. Wait 15–30 minutes after the meeting ends.
3. On the Event form, click **Teams → Fetch Recording**.
4. Expected: a green alert *"1 recording(s) found. URL saved to record."* The hidden `custom_recording_url` field on the Event is now populated.
5. Open the recording URL in a browser — it should download or stream the meeting video.
6. Repeat with **Teams → Fetch Transcript** for the text transcript.
7. If either button shows *"permission required"*, add the permissions listed above and re-authenticate.

---

## Feature 6 — Two-way Calendar Sync

### What it does

**Outlook → ERPNext:** Imports upcoming Outlook calendar events (next 30 days by default) into ERPNext as **Event** documents. Events already synced are updated in-place using `custom_outlook_event_id` as the deduplication key. Cancelled Outlook events are skipped.

**ERPNext → Outlook:** The existing **Create Teams Meeting** button (on Event/Project/Interview) pushes an ERPNext document to Outlook Calendar. `push_event_to_outlook` can also be called directly for events without a meeting link.

### Automatic sync

The **daily scheduler** calls `daily_calendar_sync()` automatically, importing the next 30 days of Outlook events into ERPNext every day.

### Manual sync (from Teams Settings)

You can also trigger calendar sync on demand by calling from the bench console:

```bash
bench --site ksa execute teams_integration.api.calendar_sync.sync_outlook_to_erpnext --kwargs '{"days_ahead": 60}'
```

### What gets imported

| Outlook field | ERPNext field |
|---|---|
| subject | subject |
| start.dateTime | starts_on |
| end.dateTime | ends_on |
| bodyPreview | description |
| onlineMeeting.joinUrl | custom_teams_meeting_url |
| id | custom_outlook_event_id |
| isAllDay | all_day |

### Limitations

- Events created by ERPNext (which already have `custom_outlook_event_id`) are updated, not duplicated.
- Attendees from Outlook are not imported as ERPNext Event Participants in the current version.
- Recurring events from Outlook are imported as separate occurrences.

### Testing

1. Create an event **directly in Microsoft Outlook** (not from ERPNext). Give it a unique title like *"Test Sync Event"*.
2. Wait for the daily scheduler, or trigger it manually:
   ```bash
   bench --site ksa execute teams_integration.api.calendar_sync.sync_outlook_to_erpnext
   ```
3. Go to **Events** in ERPNext and search for *"Test Sync Event"*.
4. Expected: the event exists with `custom_outlook_event_id` populated.
5. Update the event's subject in Outlook to *"Test Sync Event (Updated)"* and re-run sync.
6. Expected: the same ERPNext Event is updated (not duplicated) with the new subject.

---

## Feature 7 — External Guest Meeting Invite

### What it does

Adds external (non-Microsoft-365-tenant) email addresses as **required attendees** to an existing Outlook meeting. This lets you invite customers, vendors, or freelancers who don't have accounts in your Azure tenant.

### How to use

1. Open an **Event** or **Project** that already has a Teams meeting created.
2. Click **Teams → Invite External Guest**.
3. Enter one or more email addresses separated by commas (e.g. `client@example.com, vendor@partner.org`).
4. Click **Invite**.
5. The external guests receive a standard Outlook meeting invitation and can join via the Teams join link without an Azure account.

### The `custom_external_attendees` field

The email addresses you enter are saved to the `custom_external_attendees` field on the document, so you can see who has been invited externally and re-populate the dialog on the next invite.

### Limitations

- Only works for meetings created as **Outlook Calendar Events** (via the Outlook Events API). Pure Teams Online Meeting objects (`/me/onlineMeetings`) cannot have external attendees added this way.
- The button is disabled if no Outlook Event ID (`custom_outlook_event_id`) is set on the document.

### Testing

1. Create a Teams meeting from an **Event** form.
2. Click **Teams → Invite External Guest** and enter an external email (e.g. a Gmail address you have access to).
3. Check that external email inbox — an Outlook meeting invitation should arrive.
4. The `custom_external_attendees` field on the Event form should now list that email.
5. Click **Invite External Guest** again — the dialog should pre-populate with the saved email.
6. Send a second external address — verify both now appear in the field and in Outlook's attendee list.

---

## Feature 8 — Teams Activity Report

### What it does

A built-in **Script Report** at **Reports → Teams Activity** that shows messaging activity across all users and conversations stored in ERPNext.

### Columns

| Column | Description |
|---|---|
| Employee / Sender | Display name of the Teams user |
| Sent | Messages sent from ERPNext (Outbound) |
| Received | Messages received from Teams (Inbound) |
| Conversations | Number of distinct chats the user appears in |
| Last Active | Timestamp of their most recent message |

### Filters

| Filter | Effect |
|---|---|
| From Date | Only messages on or after this date |
| To Date | Only messages on or before this date |
| Chat Type | Inbound only / Outbound only / All (default) |

### How to access

1. Go to **Reports** in ERPNext and search **Teams Activity**.  
   Or navigate directly: `/app/query-report/Teams Activity`

### Testing

1. Send several messages via the Teams Chat page and via document-level group chats.
2. Open the **Teams Activity** report.
3. Verify rows appear for each sender, with correct sent/received counts.
4. Apply a **From Date** filter — rows with `last_active` before that date should disappear.
5. Set both **From Date** and **To Date** to today — only today's activity should show.
6. Click **Export** (Excel/CSV) — the data should download cleanly.

---

## Additional Azure Permissions Summary

The base installation requires a set of permissions. The advanced features add:

| Permission | Feature | Type |
|---|---|---|
| `Presence.Read.All` | Feature 3 — Presence Status | Delegated |
| `OnlineMeetingRecording.Read.All` | Feature 5 — Recordings | Delegated |
| `OnlineMeetingTranscript.Read.All` | Feature 5 — Transcripts | Delegated |

After adding any new permission in Azure Portal, you must **re-authenticate** in Teams Settings to include the new scopes in your token.

---

## Error Handling Notes

All feature errors are logged in **Settings → Error Log** with descriptive titles:

| Log Title | Related Feature |
|---|---|
| Teams Realtime Subscribe Error | Feature 1 |
| Teams Subscription Renewal Error | Feature 1 |
| Teams Adaptive Card Error | Feature 2 |
| Teams Presence Error | Feature 3 |
| Teams Workflow Notification Error | Feature 4 |
| Teams Recording Fetch Error | Feature 5 |
| Teams Transcript Fetch Error | Feature 5 |
| Teams Calendar Sync Error | Feature 6 |
| Teams Calendar Import Error | Feature 6 |
