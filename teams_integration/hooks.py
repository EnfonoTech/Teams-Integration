app_name = "teams_integration"
app_title = "Teams Integration"
app_publisher = "siva@enfono.com"
app_description = "ERPNext and MS Teams Integration App"
app_email = "siva@enfono.com"
app_license = "mit"
# Copyright (c) 2026, siva@enfono.com

doctype_js = {
	"Project":   "public/js/project_teams_chat.js",
	"Event":     "public/js/event_teams_chat.js",
	"Interview": "public/js/interview_teams.js",
	"Employee":  "public/js/employee_teams.js",
}

after_install = "teams_integration.install.after_install"

# Feature 4: Detect workflow state changes on any doctype and notify Teams
doc_events = {
	"*": {
		"before_save": "teams_integration.api.notifications.before_doc_save",
		"on_update":   "teams_integration.api.notifications.on_doc_update",
	}
}

scheduler_events = {
	"hourly": [
		"teams_integration.api.chat.sync_all_conversations",
		# Feature 1: renew short-lived chat webhook subscriptions
		"teams_integration.api.realtime_notify.renew_all_chat_subscriptions",
	],
	"daily": [
		"teams_integration.api.auth.renew_graph_subscriptions",
		# Feature 6: import Outlook calendar events into ERPNext
		"teams_integration.api.calendar_sync.daily_calendar_sync",
	],
}

fixtures = [
	{"doctype": "Custom Field", "filters": [["module", "in", ("Teams Integration",)]]}
]
