package com.smsledger.app

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.progressindicator.LinearProgressIndicator
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/** The month at a glance: net, in and out, balances, a 14-day chart and where the money went. */
class HomeScreen(
    parent: ViewGroup,
    private val prefs: Prefs,
    private val openAttention: () -> Unit,
) {
    val view: View = LayoutInflater.from(parent.context).inflate(R.layout.screen_home, parent, false)
    private val ctx = parent.context
    private val month = Calendar.getInstance()
    private val refresh = view.findViewById<SwipeRefreshLayout>(R.id.refresh)

    init {
        refresh.setOnRefreshListener { load() }
        view.findViewById<View>(R.id.prev_month).setOnClickListener { shiftMonth(-1) }
        view.findViewById<View>(R.id.next_month).setOnClickListener { shiftMonth(1) }
        view.findViewById<View>(R.id.attention).setOnClickListener { openAttention() }
        showMonthTitle()
        prefs.cachedDashboard.takeIf { it.isNotEmpty() }?.let { render(JSONObject(it), prefs.cachedDashboardAt) }
    }

    fun load() {
        if (!prefs.isConfigured) {
            refresh.isRefreshing = false
            view.findViewById<TextView>(R.id.updated).text = "Connect to ERPNext under Settings to see your money here."
            return
        }
        refresh.isRefreshing = true
        val key = monthKey()
        Background.run({ ErpClient(prefs).dashboard(key) }) { result ->
            refresh.isRefreshing = false
            result.onSuccess { board ->
                if (isCurrentMonth()) {
                    prefs.cachedDashboard = board.toString()
                    prefs.cachedDashboardAt = System.currentTimeMillis()
                }
                render(board, System.currentTimeMillis())
            }.onFailure {
                view.findViewById<TextView>(R.id.updated).text = "Offline: ${it.message ?: "could not reach ERPNext"}"
            }
        }
    }

    private fun shiftMonth(by: Int) {
        val next = (month.clone() as Calendar).apply { add(Calendar.MONTH, by) }
        if (next.after(Calendar.getInstance())) return
        month.time = next.time
        showMonthTitle()
        load()
    }

    private fun render(board: JSONObject, at: Long) {
        val hidden = prefs.hideAmounts
        val currency = board.optString("currency", "KES")
        val totals = board.optJSONObject("totals") ?: JSONObject()
        val net = totals.optDouble("net", 0.0)
        text(R.id.net, Money.format(net, currency, hidden))
        view.findViewById<TextView>(R.id.net).setTextColor(color(if (net >= 0) R.color.money_in else R.color.money_out))
        text(R.id.total_in, Money.format(totals.optDouble("in", 0.0), currency, hidden))
        text(R.id.total_out, Money.format(totals.optDouble("out", 0.0), currency, hidden))
        text(R.id.total_charges, Money.format(totals.optDouble("charges", 0.0), currency, hidden))
        renderAttention(board.optInt("attention", 0))
        renderBalances(board.optJSONArray("balances") ?: JSONArray(), currency, hidden)
        renderChart(board.optJSONArray("daily") ?: JSONArray())
        renderRanking(R.id.payees, board.optJSONArray("top_payees") ?: JSONArray(), currency, hidden)
        renderRanking(R.id.categories, board.optJSONArray("top_accounts") ?: JSONArray(), currency, hidden)
        text(R.id.updated, "Updated " + SimpleDateFormat("d MMM, HH:mm", Locale.getDefault()).format(Date(at)))
    }

    private fun renderAttention(count: Int) {
        view.findViewById<View>(R.id.attention).visibility = if (count > 0) View.VISIBLE else View.GONE
        text(R.id.attention_text, "$count message${if (count == 1) "" else "s"} could not be recorded. Tap to fix.")
    }

    private fun renderBalances(rows: JSONArray, currency: String, hidden: Boolean) {
        val box = clearBelowLabel(R.id.balances)
        if (rows.length() == 0) box.addView(muted("No balance seen in a message yet"))
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            box.addView(pair(row.optString("source"), Money.format(row.optDouble("balance"), currency, hidden)))
        }
    }

    private fun renderChart(daily: JSONArray) {
        val parse = SimpleDateFormat("yyyy-MM-dd", Locale.US)
        val label = SimpleDateFormat("d", Locale.getDefault())
        val days = (0 until daily.length()).map {
            val d = daily.getJSONObject(it)
            val day = runCatching { label.format(parse.parse(d.optString("date"))!!) }.getOrDefault("")
            BarChartView.Day(day, d.optDouble("in", 0.0), d.optDouble("out", 0.0))
        }
        view.findViewById<BarChartView>(R.id.chart).setDays(days)
    }

    /** Each line with a bar showing its share of the biggest one. */
    private fun renderRanking(boxId: Int, rows: JSONArray, currency: String, hidden: Boolean) {
        val box = clearBelowLabel(boxId)
        if (rows.length() == 0) box.addView(muted("No spending recorded this month"))
        val top = (0 until rows.length()).maxOfOrNull { rows.getJSONObject(it).optDouble("amount") } ?: 1.0
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val amount = row.optDouble("amount")
            box.addView(pair(row.optString("label").substringBeforeLast(" - "), Money.format(amount, currency, hidden)))
            box.addView(LinearProgressIndicator(ctx).apply {
                max = 100
                progress = ((amount / top) * 100).toInt().coerceIn(2, 100)
                setIndicatorColor(color(R.color.money_out))
            })
        }
    }

    private fun clearBelowLabel(id: Int): LinearLayout =
        view.findViewById<LinearLayout>(id).apply { if (childCount > 1) removeViews(1, childCount - 1) }

    private fun pair(left: String, right: String): View = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        setPadding(0, dp(8), 0, dp(4))
        addView(TextView(ctx).apply { text = left; textSize = 14f },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        addView(TextView(ctx).apply { text = right; textSize = 14f; setTypeface(typeface, android.graphics.Typeface.BOLD) })
    }

    private fun muted(message: String) = TextView(ctx).apply {
        text = message
        setTextColor(color(R.color.muted))
        setPadding(0, dp(8), 0, 0)
    }

    private fun showMonthTitle() = text(R.id.month, SimpleDateFormat("MMMM yyyy", Locale.getDefault()).format(month.time))
    private fun monthKey() = SimpleDateFormat("yyyy-MM", Locale.US).format(month.time)
    private fun isCurrentMonth() = monthKey() == SimpleDateFormat("yyyy-MM", Locale.US).format(Date())
    private fun text(id: Int, value: String) { view.findViewById<TextView>(id).text = value }
    private fun color(id: Int) = ContextCompat.getColor(ctx, id)
    private fun dp(v: Int) = (v * ctx.resources.displayMetrics.density).toInt()
}
