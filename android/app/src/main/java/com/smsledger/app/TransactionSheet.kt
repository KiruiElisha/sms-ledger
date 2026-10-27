package com.smsledger.app

import android.app.Activity
import android.view.LayoutInflater
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.ContextCompat
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import org.json.JSONObject

/** One message in full, with Retry and Change account. Calls [changed] with the server's new copy. */
class TransactionSheet(
    private val activity: Activity,
    private val prefs: Prefs,
    private val changed: (JSONObject) -> Unit,
) {
    private var accounts: List<Pair<String, String>>? = null

    fun show(t: JSONObject) {
        val view = LayoutInflater.from(activity).inflate(R.layout.sheet_transaction, null)
        val dialog = BottomSheetDialog(activity).apply { setContentView(view) }
        bind(view, t)
        view.findViewById<View>(R.id.retry).setOnClickListener {
            act(dialog, "Retrying…") { ErpClient(prefs).retry(t.optString("name")) }
        }
        view.findViewById<View>(R.id.recategorise).setOnClickListener { pickAccount(dialog, t) }
        dialog.show()
    }

    private fun bind(view: View, t: JSONObject) {
        val amount = view.findViewById<TextView>(R.id.amount)
        amount.text = Transactions.signedAmount(t)
        amount.setTextColor(ContextCompat.getColor(activity, Transactions.amountColor(t)))
        view.findViewById<TextView>(R.id.title).text = Transactions.title(t)
        view.findViewById<TextView>(R.id.details).text = Transactions.details(t)
        view.findViewById<TextView>(R.id.message).text = t.optString("message")
        val error = t.optString("error").takeIf { it.isNotBlank() && it != "null" && t.optString("status") != "Posted" }
        view.findViewById<TextView>(R.id.error).apply {
            visibility = if (error != null) View.VISIBLE else View.GONE
            text = error?.substringBefore("\n\n")
        }
        view.findViewById<View>(R.id.retry).visibility =
            if (Transactions.needsAttention(t) || t.optString("status") in setOf("Pending", "Parsed")) View.VISIBLE else View.GONE
        view.findViewById<View>(R.id.recategorise).visibility =
            if (t.optInt("is_transfer") == 1 || t.optString("status") == "Linked") View.GONE else View.VISIBLE
    }

    private fun pickAccount(dialog: BottomSheetDialog, t: JSONObject) {
        val cached = accounts
        if (cached != null) return chooseFrom(cached, dialog, t)
        Background.run({ ErpClient(prefs).accounts() }) { result ->
            result.onSuccess { arr ->
                val list = (0 until arr.length()).map {
                    val a = arr.getJSONObject(it)
                    a.optString("name") to "${a.optString("account_name")} (${a.optString("root_type")})"
                }
                accounts = list
                chooseFrom(list, dialog, t)
            }.onFailure { toast(it.message ?: "Could not load accounts") }
        }
    }

    private fun chooseFrom(list: List<Pair<String, String>>, dialog: BottomSheetDialog, t: JSONObject) {
        MaterialAlertDialogBuilder(activity)
            .setTitle("File under")
            .setItems(list.map { it.second }.toTypedArray()) { _, i -> askRemember(list[i], dialog, t) }
            .show()
    }

    private fun askRemember(account: Pair<String, String>, dialog: BottomSheetDialog, t: JSONObject) {
        val payee = Transactions.title(t)
        val name = t.optString("name")
        val save = { remember: Boolean ->
            act(dialog, "Re-posting…") { ErpClient(prefs).recategorise(name, account.first, remember) }
        }
        MaterialAlertDialogBuilder(activity)
            .setTitle(account.second)
            .setMessage("Use this account for every message from $payee from now on?")
            .setPositiveButton("Always for $payee") { _, _ -> save(true) }
            .setNegativeButton("Just this one") { _, _ -> save(false) }
            .show()
    }

    private fun act(dialog: BottomSheetDialog, progress: String, call: () -> JSONObject) {
        toast(progress)
        Background.run(call) { result ->
            result.onSuccess { updated ->
                dialog.dismiss()
                changed(updated)
                toast("Now ${updated.optString("status")}")
            }.onFailure { toast(it.message ?: "Failed") }
        }
    }

    private fun toast(message: String) = Toast.makeText(activity, message, Toast.LENGTH_SHORT).show()
}
