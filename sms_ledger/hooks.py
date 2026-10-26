app_name = "sms_ledger"
app_title = "SMS Ledger"
app_publisher = "Sol"
app_description = "Post M-PESA and bank SMS alerts (KCB and others) to ERPNext as accounting entries"
app_email = "cursor953@gmail.com"
app_license = "mit"

required_apps = ["erpnext"]

after_install = "sms_ledger.install.after_install"
after_migrate = "sms_ledger.install.ensure_role"

scheduler_events = {
	"hourly": [
		"sms_ledger.posting.process_pending",
	],
}
