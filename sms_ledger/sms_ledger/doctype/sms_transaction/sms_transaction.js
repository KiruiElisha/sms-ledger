// Copyright (c) 2026, Sol and contributors
// For license information, please see license.txt

frappe.ui.form.on("SMS Transaction", {
	refresh(frm) {
		frm.disable_save();
		if (frm.doc.use_manual_values) frm.enable_save();

		const label = ["Posted", "Linked"].includes(frm.doc.status) ? __("Re-process") : __("Process");
		frm.add_custom_button(label, () => {
			const run = () =>
				frappe.call({
					method: "sms_ledger.api.reprocess",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Processing..."),
				}).then((r) => {
					const res = r.message || {};
					frappe.show_alert({
						message: __("Status: {0}", [res.status]),
						indicator: res.status === "Failed" ? "red" : "green",
					});
					frm.reload_doc();
				});
			if (["Posted", "Linked"].includes(frm.doc.status)) {
				frappe.confirm(
					__("Entries already made for this message will be cancelled and posted again. Continue?"),
					run
				);
			} else {
				run();
			}
		});

		["journal_entry", "payment_entry", "charges_entry"].forEach((f) => {
			if (frm.doc[f]) {
				const doctype = f === "payment_entry" ? "Payment Entry" : "Journal Entry";
				frm.add_custom_button(frm.fields_dict[f].df.label, () =>
					frappe.set_route("Form", doctype, frm.doc[f]), __("View"));
			}
		});
		if (frm.doc.party) {
			frm.add_custom_button(__("Party"), () =>
				frappe.set_route("Form", frm.doc.party_type, frm.doc.party), __("View"));
		}
	},

	use_manual_values(frm) {
		if (frm.doc.use_manual_values) frm.enable_save();
	},
});
