// Copyright (c) 2026, Sol and contributors
// For license information, please see license.txt

frappe.listview_settings["SMS Transaction"] = {
	add_fields: ["status", "direction", "amount"],
	get_indicator(doc) {
		const colors = {
			Pending: "orange",
			Parsed: "blue",
			Posted: "green",
			Linked: "cyan",
			Ignored: "gray",
			Unparsed: "yellow",
			Failed: "red",
		};
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
	onload(listview) {
		listview.page.add_action_item(__("Process"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) return;
			frappe.call({
				method: "sms_ledger.api.process_selected",
				args: { names },
				freeze: true,
				freeze_message: __("Processing {0} messages...", [names.length]),
			}).then(() => listview.refresh());
		});
	},
};
