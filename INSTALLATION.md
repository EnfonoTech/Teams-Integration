# Teams Integration — Installation & Testing Guide

**App:** `teams_integration`  
**Author:** siva@enfono.com  
**Compatibility:** Frappe / ERPNext v15+

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1 — Azure App Registration](#step-1--register-a-microsoft-azure-app)
3. [Step 2 — Install the App](#step-2--install-the-app)
4. [Step 3 — Configure Teams Settings](#step-3--configure-teams-settings)
5. [Step 4 — Admin Authentication](#step-4--authenticate-admin-account-with-teams)
6. [Step 5 — Link Employees to Azure](#step-5--link-employees-to-microsoft-accounts)
7. [Step 6 — Employee Personal Authentication](#step-6--employee-personal-authentication-optional)
8. [Step 7 — Feature Reference](#step-7--feature-reference)
9. [Teams Chat Page](#teams-chat-page)
10. [Scheduled Tasks](#scheduled-tasks)
11. [Use Cases & Test Scenarios](#use-cases--test-scenarios)
12. [Troubleshooting](#troubleshooting)
13. [Uninstall](#uninstall)

---

## Prerequisites

- Frappe bench with ERPNext v15+ installed and running
- Microsoft Azure account with permission to register apps (tenant admin)
- All employees must have a Microsoft 365 / Azure AD account in the same tenant
- Python 3.10+
- Public HTTPS URL for the site (required for OAuth redirect and webhooks)

---

## Step 1 — Register a Microsoft Azure App

1. Open [Azure Portal → App Registrations](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) and click **New registration**.
2. Name it (e.g., `ERPNext Teams Integration`). Choose **Accounts in this organizational directory only**.
3. Under **Redirect URI**, choose **Web** and enter:
   ```
   https://<your-site-domain>/api/method/teams_integration.api.auth.callback
   ```
4. After creation, copy:
   - **Application (client) ID** → used as *Client ID*
   - **Directory (tenant) ID** → used as *Tenant ID*
5. Go to **Certificates & secrets → New client secret**, set an expiry, copy the **Value** → *Client Secret*.
6. Go to **API permissions → Add a permission → Microsoft Graph → Delegated permissions** and add all of the following:

   | Permission | Purpose |
   |---|---|
   | `User.Read` | Read authenticated user's profile |
   | `User.ReadBasic.All` | Look up other users' Azure IDs by email |
   | `offline_access` | Keep tokens alive via refresh |
   | `Chat.ReadWrite` | Read and write group/direct chats |
   | `Chat.Create` | Create new group and 1:1 chats |
   | `Chat.ReadBasic` | List chat metadata |
   | `ChannelMessage.Send` | Post messages to Teams channels |
   | `OnlineMeetings.ReadWrite` | Create and manage Teams meetings |
   | `Calendars.ReadWrite` | Create Outlook calendar events with meeting links |

7. Click **Grant admin consent** for your organization and confirm.

---

## Step 2 — Install the App

```bash
cd /home/<user>/frappe-bench

# From local disk
bench get-app /path/to/teams_integration

# Or from a git remote
# bench get-app https://github.com/your-org/teams_integration --branch main

# Install on your site
bench --site <your-site-name> install-app teams_integration

# Run migration — creates doctypes, custom fields, and database indexes
bench --site <your-site-name> migrate

# Build frontend assets
bench build --app teams_integration
```

After migration the following are created automatically:

- **Doctypes:** Teams Settings, Teams Conversation, Teams Chat Message, Teams Enabled Doctype
- **Custom fields on Employee:** Microsoft Teams section, Azure Object ID, personal token fields (hidden)
- **Custom fields on Project / Event / Interview:** Outlook Event ID, Teams Chat ID, Teams Meeting URL, Join Teams Meeting button
- **Frappe Page:** `/app/teams-chat` — the central Teams Chat interface

---

## Step 3 — Configure Teams Settings

1. In ERPNext, go to **Teams Settings** (search in the navbar).
2. Fill in the credentials from Step 1:
   - **Client ID**
   - **Client Secret**
   - **Tenant ID**
   - **Redirect URI** — auto-populated from your site URL; must match the Azure redirect URI exactly
3. In the **Enabled Doctypes** table, add the doctypes to enable Teams actions on:
   - `Event`
   - `Project`
   - `Interview` *(only available if ERPNext HR module is installed)*
4. Click **Save**.

---

## Step 4 — Authenticate Admin Account with Teams

This is the **shared/admin token** — used for group chats, meetings, channel posts, and admin-initiated direct messages.

1. In **Teams Settings**, click **Authenticate with Teams** (the primary blue button).
2. You will be redirected to Microsoft login.
3. Sign in with the Microsoft 365 account that will act as the integration owner (e.g., `erpnext@company.com`).
4. After consent, you are redirected back to Teams Settings with a green flash message.
5. Under **More Actions**, click **Test Connection** to verify all permissions are working.
6. Also run **Sync Actions → Validate Configuration** to confirm all required settings are present.

> This account's identity appears as the sender in admin-initiated direct messages and group chats.

---

## Step 5 — Link Employees to Microsoft Accounts

The app matches ERPNext Employees to their Azure AD identity using the `azure_object_id` field.

### Option A — Bulk Sync (Recommended for initial setup)

In **Teams Settings → Sync Actions → Sync Azure IDs**.  
The app fetches all users from your Microsoft tenant and matches them by `company_email` or `personal_email` on the Employee record.

### Option B — Per-employee manual sync

1. Open any **Employee** record.
2. Click **Teams → Sync Teams Azure ID**.
3. The app looks up the employee's email in Azure AD and saves the Object ID.

> **Verify:** On the Employee form, the dashboard should show a green **"Teams Linked"** indicator after the sync.

---

## Step 6 — Employee Personal Authentication (Optional)

This enables true **employee-to-employee direct messaging** — messages appear in Teams as sent by the employee themselves, not by the admin account.

Each employee does this once from **their own Employee record**:

1. Open **your own** Employee record (HR → Employees → find yourself).
2. In the **My Teams** button group, click **Connect My Teams Account**.
3. You are redirected to Microsoft login — sign in with **your personal Microsoft 365 account**.
4. After consent, you land back on your Employee form with a green **"Teams: Personally Connected"** indicator.

Once connected:

- The **My Teams → Send Message To...** button appears.
- Click it, select any Employee, type your message.
- The message arrives in Teams as **you → recipient** (true peer-to-peer).

> **Note:** If you see **"My Teams"** button group on your Employee form, it means the system detected this is your record. Other employees' records show the admin-facing Teams buttons instead.

---

## Step 7 — Feature Reference

### Event, Project, and Interview forms

A **Teams** button group appears on any saved document whose doctype is enabled in Teams Settings:

| Button | Action |
|---|---|
| Create Teams Chat | Creates a group chat with all participants; saves Chat ID on the document |
| Open Teams Chat | Shows the locally synced message history in a dialog |
| Send Teams Message | Sends a message to the linked group chat |
| Post to Channel | Posts a message to any Teams channel (enter Team ID + Channel ID) |
| Create Teams Meeting | Creates an Outlook Calendar event with a Teams join link |
| Reschedule Teams Meeting | Updates the meeting time to match the document's current dates |
| Cancel Teams Meeting | Cancels and removes the meeting from Outlook/Teams |
| Sync Now | Pulls latest messages from Teams into local history immediately |

### Employee form — Admin buttons (HR managers / admins)

Visible on any Employee record for users with HR manager access:

| Button | Action |
|---|---|
| Sync Teams Azure ID | Fetches and caches the Azure Object ID for this employee |
| Clear Teams Azure ID | Clears the stored Azure Object ID |
| Start Direct Chat | Creates or retrieves a 1:1 Teams chat (via admin token) |
| Send Direct Message | Prompts for a message and sends it to this employee (via admin token) |
| Open Direct Chat | Fetches and displays the direct chat history in a dialog |

### Employee form — My Teams buttons (self-service, own record only)

Visible only when the logged-in user is viewing **their own** Employee record:

| Button | Action |
|---|---|
| Connect My Teams Account | Triggers per-employee OAuth — sign in with your Microsoft account |
| Send Message To... | Sends a peer-to-peer direct message using **your** Teams identity |
| Disconnect My Teams | Removes your stored personal tokens |

### Teams Chat page (`/app/teams-chat`)

A dedicated chat interface showing all conversations:

- **Left sidebar:** All group chats (linked to Projects, Events, Interviews) and direct chats (linked to Employees), searchable
- **Right panel:** Full message history with sender-styled bubbles (blue = outbound, grey = inbound)
- **Input bar:** Type a message, press Enter or click Send — sends via admin token to the selected chat
- **Sync All button:** Pulls fresh messages from Teams API for all known conversations

---

## Teams Chat Page

Navigate to `/app/teams-chat` from the Frappe navbar or search.

The page loads all `Teams Conversation` records, grouped as:
- **Group Chats** — conversations linked to a Project, Event, or Interview
- **Direct Messages** — 1:1 conversations linked to an Employee

Click any conversation to open the message history. The page does **not** auto-refresh — use the **Sync All** button to pull new messages, or rely on the hourly background sync.

---

## Scheduled Tasks

These run automatically in the background:

| Schedule | Task |
|---|---|
| Hourly | Sync all Teams conversation messages into local `Teams Chat Message` records |
| Daily | Renew the Microsoft Graph webhook subscription (keeps RSVP sync alive for Events) |

---

## Use Cases & Test Scenarios

These tests verify that the app is installed and configured correctly. Run them in order after completing the setup above.

---

### Test 1 — Sync Azure IDs for employees

**Goal:** Ensure all employees are linked to their Microsoft 365 accounts.

**Steps:**
1. Open any **Employee** record that has a `Company Email` or `Personal Email` set.
2. Click **Teams → Sync Teams Azure ID**.

**Expected result:**  
The **Teams Azure Object ID** field is populated. The dashboard shows **"Teams Linked"** in green.

---

### Test 2 — Group chat on a Project

**Goal:** Create a group Teams chat linked to a Project.

**Steps:**
1. Open any **Project** that has at least 2 team members with synced Azure IDs.
2. Click **Teams → Create Teams Chat**.

**Expected result:**  
- Green flash: *"Teams chat created and linked."*
- The **Teams Chat ID** field on the Project is populated.
- In Microsoft Teams, a new group chat appears with the linked team members.

---

### Test 3 — Send a message to the group chat

**Goal:** Send a plain-text message from ERPNext to the Teams group chat.

**Steps:**
1. On the same Project form, click **Teams → Send Teams Message**.
2. Type a test message and click **Send**.

**Expected result:**  
- Flash: *"Message sent to Teams."*
- In Microsoft Teams, the message appears in the group chat.

---

### Test 4 — Sync conversation and open it

**Goal:** Confirm local message history is populated.

**Steps:**
1. On the Project form, click **Teams → Sync Now**.
2. Then click **Teams → Open Teams Chat**.

**Expected result:**  
The dialog shows the messages from Test 3 with correct timestamps and sender names.

---

### Test 5 — Create a Teams meeting on an Event

**Goal:** Create an Outlook/Teams meeting from an ERPNext Event.

**Steps:**
1. Create a new **Event** with a future `starts_on` date; add at least one participant whose email is in your tenant.
2. Save the Event.
3. Click **Teams → Create Teams Meeting**.

**Expected result:**  
- The **Teams Meeting URL** field is populated.
- A **Join Teams Meeting** button appears on the Event form.
- In Outlook / Teams Calendar, the meeting appears with the correct title, time, and attendees.

---

### Test 6 — Admin direct message to an employee

**Goal:** Send a direct Teams message to an employee using the admin token.

**Steps:**
1. Open any **Employee** record (as HR Manager or System Manager).
2. Click **Teams → Send Direct Message**.
3. Type a test message and click **Send**.

**Expected result:**  
- Flash: *"Message sent to [Employee Name]."*
- In Microsoft Teams, the admin account's direct chat with that employee shows the new message.

---

### Test 7 — Employee personal authentication

**Goal:** An employee connects their own Microsoft account for peer-to-peer messaging.

**Steps:**
1. Log in as a regular employee user (not admin).
2. Open **your own** Employee record (HR → Employees → search your name).
3. In the **My Teams** button group, click **Connect My Teams Account**.
4. Complete the Microsoft login with your personal work account.

**Expected result:**  
- Redirected back to your Employee form.
- Green flash: *"Teams personal account connected!"*
- Dashboard shows **"Teams: Personally Connected"** in green.
- **My Teams → Send Message To...** button appears.

---

### Test 8 — Peer-to-peer direct message

**Goal:** An employee sends a message to a colleague that appears as coming from them (not the admin) in Teams.

**Prerequisites:** Both employees must have their Azure Object IDs synced (Test 1) and the sender must have completed Test 7.

**Steps:**
1. Logged in as the employee from Test 7, click **My Teams → Send Message To...**.
2. Select a colleague's Employee record and type a message.

**Expected result:**  
- Flash: *"Message sent via your Teams account!"*
- In Microsoft Teams, the recipient sees a direct message **from the sender's own Teams identity** — not from the admin account.

---

### Test 9 — Teams Chat page

**Goal:** Verify the central chat page shows all conversations and can send messages.

**Steps:**
1. Navigate to `/app/teams-chat` (search *"Teams Chat"* in the navbar).
2. Confirm the sidebar lists the group chat from Test 2 and the direct chat from Test 6.
3. Click a conversation, type a message, and press **Enter**.

**Expected result:**  
- Message history loads with correct bubble styling.
- After sending, the new message appears immediately.
- Clicking **Sync All** refreshes the history from Teams.

---

### Test 10 — Hourly background sync

**Goal:** Confirm the scheduler pulls new messages automatically.

**Steps:**
1. Send a message **directly in Microsoft Teams** (not via ERPNext) to the group chat from Test 2.
2. Wait for the hourly scheduler, or trigger it manually:
   ```bash
   bench --site ksa execute teams_integration.api.chat.sync_all_conversations
   ```
3. Open the **Teams Chat** page and select the group chat.

**Expected result:**  
The message sent from Teams appears in the local history with direction **"Inbound"** and the sender's display name.

---

> For advanced feature testing (real-time notifications, adaptive cards, presence, workflow alerts, calendar sync, recordings, external guests, activity report) see **[FEATURES.md](FEATURES.md)**.

---

## Troubleshooting

### Migration fails with `KeyError: 'name'`

The fixture JSON is missing `name` fields. Ensure you are on the latest version of the app and re-run `bench migrate`.

### `403 Permission Denied` when creating a meeting

The admin token lacks `Calendars.ReadWrite`. Re-authenticate:  
Teams Settings → **Authenticate with Teams** → sign in again and re-grant all permissions.

### `No valid access token` errors

The refresh token is expired. Go to **Teams Settings → Authenticate with Teams** and re-authenticate.

### `No Employee record linked to your account`

When clicking **Connect My Teams Account**, this means your ERPNext **User** is not linked to an Employee. Ask HR to set your `user_id` on your Employee record, or ensure your login email matches the Employee's `company_email`.

### Azure ID not found for an employee

- The employee's **Company Email** or **Personal Email** must exactly match their Microsoft 365 UPN (e.g. `firstname.lastname@company.com`).
- The account must be in the **same tenant** configured in Teams Settings.

### `Could not resolve your Azure ID` on personal message send

Your own Employee record has no Azure Object ID. After connecting your personal account, also run **Teams → Sync Teams Azure ID** on your Employee form.

### Webhook / RSVP sync not working

Graph API webhooks require a publicly accessible HTTPS URL. For local development, use [ngrok](https://ngrok.com/) and temporarily set the Redirect URI to the ngrok address.

### Interview doctype fields skipped during migrate

This is expected if the ERPNext HR module is not installed on the site. The app skips Interview fixtures gracefully — all other doctypes work normally.

---

## Uninstall

```bash
bench --site <your-site-name> uninstall-app teams_integration
bench --site <your-site-name> migrate
```

Custom fields on Employee, Project, Event, and Interview are **preserved** after uninstall to protect existing data. To remove them manually, go to **Customize Form** for each doctype.

---

## Support

Maintained by **siva@enfono.com**.  
For issues, check the Frappe error log at **Settings → Error Log**.
