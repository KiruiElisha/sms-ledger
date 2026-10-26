// Copyright (c) 2026, Sol and contributors
// For license information, please see license.txt

frappe.ui.form.on("SMS Source", {
	setup(frm) {
		frm.set_query("account", () => ({
			filters: { is_group: 0, account_type: ["in", ["Bank", "Cash"]] },
		}));
		frm.set_query("bank_account", () => ({
			filters: { is_company_account: 1 },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Test Message"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Test a Message"),
				fields: [
					{
						fieldname: "sender",
						fieldtype: "Data",
						label: __("Sender (optional)"),
						default: (frm.doc.senders || [])[0]?.sender_id,
						description: __("Checks which source would accept the message."),
					},
					{ fieldname: "message", fieldtype: "Small Text", label: __("Message"), reqd: 1 },
					{ fieldname: "result", fieldtype: "HTML" },
				],
				primary_action_label: __("Parse"),
				primary_action(values) {
					frappe.call({
						method: "sms_ledger.api.test_parse",
						args: { source: frm.doc.name, message: values.message, sender: values.sender },
					}).then((r) => {
						const res = r.message || {};
						let html = "";
						if (values.sender) {
							html += `<p><b>${__("Accepted by source")}:</b> ${
								frappe.utils.escape_html(res.accepted_by_source || __("none"))
							}</p>`;
						}
						if (!res.parsed) {
							html += `<p class="text-danger">${__("No transaction found in this message.")}</p>`;
						} else {
							html += '<table class="table table-bordered table-sm">';
							Object.entries(res.parsed).forEach(([k, v]) => {
								if (v === null || v === "") return;
								html += `<tr><td>${frappe.utils.escape_html(k)}</td><td>${
									frappe.utils.escape_html(String(v))
								}</td></tr>`;
							});
							html += "</table>";
						}
						d.fields_dict.result.$wrapper.html(html);
					});
				},
			});
			d.show();
		});
		frm.add_custom_button(__("Messages"), () =>
			frappe.set_route("List", "SMS Transaction", { source: frm.doc.name }));
	},
});
