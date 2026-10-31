package com.smsledger.app

import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.progressindicator.LinearProgressIndicator
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/** The month against the last, six months of in and out, and where the money came from and went. */
class InsightsScreen(parent: ViewGroup, private val prefs: Prefs) {
    val view: View = LayoutInflater.from(parent.context).inflate(R.layout.screen_insights, parent, false)
    private val ctx = parent.context
    private val month = Calendar.getInstance()
    private val refresh = view.findViewById<SwipeRefreshLayout>(R.id.insights_refresh)
    private val content = view.findViewById<LinearLayout>(R.id.insights_content)
    private val palette = listOf(R.color.chart_1, R.color.chart_2, R.color.chart_3, R.color.chart_4, R.color.chart_5, R.color.chart_6)
        .map { ContextCompat.getColor(ctx, it) }
    private var currency = "KES"

    init {
        refresh.setOnRefreshListener { load() }
        prefs.cachedInsights.takeIf { it.isNotEmpty() }?.let { cached -> runCatching { render(JSONObject(cached)) } }
    }

    fun load() {
        if (!prefs.isConfigured) {
            refresh.isRefreshing = false
            content.removeAllViews()
            content.addView(muted("Connect to ERPNext under Settings to see your insights here."))
            return
        }
        refresh.isRefreshing = true
        val key = monthKey()
        Background.run({ ErpClient(prefs).insights(key) }) { result ->
            refresh.isRefreshing = false
            result.onSuccess { data ->
                if (isCurrentMonth()) prefs.cachedInsights = data.toString()
                render(data)
            }.onFailure {
                if (content.childCount == 0) content.addView(header())
                content.addView(muted("Offline: ${it.message ?: "could not reach ERPNext"}"), 1)
            }
        }
    }

    private fun render(data: JSONObject) {
        currency = data.optString("currency", "KES")
        val totals = data.optJSONObject("totals") ?: JSONObject()
        val change = data.optJSONObject("change") ?: JSONObject()
        content.removeAllViews()
        content.addView(header())
        content.addView(tiles(totals, change))
        content.addView(stats(data.optJSONObject("stats") ?: JSONObject()))
        content.addView(trend(data.optJSONArray("trend") ?: JSONArray()))
        content.addView(categories(data.optJSONArray("categories") ?: JSONArray(), totals.optDouble("out", 0.0)))
        content.addView(ranking("Where money came from", data.optJSONArray("sources") ?: JSONArray(), R.color.money_in, "No money came in this month"))
        content.addView(ranking("Spending by day of the week", data.optJSONArray("weekdays") ?: JSONArray(), R.color.chart_2, "No spending this month"))
        content.addView(biggest(data.optJSONArray("biggest") ?: JSONArray()))
    }

    // ── Sections ──────────────────────────────────────────────────────────────

    private fun header(): View = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(arrow("‹", "Previous month") { shiftMonth(-1) })
        addView(TextView(ctx).apply {
            text = SimpleDateFormat("MMMM yyyy", Locale.getDefault()).format(month.time)
            textSize = 18f
            gravity = Gravity.CENTER
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(color(R.color.ink))
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        addView(arrow("›", "Next month") { shiftMonth(1) })
    }

    /** In, out, net and charges, each against last month. Up is good for in and net, bad for out and charges. */
    private fun tiles(totals: JSONObject, change: JSONObject): View {
        val grid = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        val specs = listOf(
            Triple("Money in", "in", true),
            Triple("Money out", "out", false),
            Triple("Net", "net", true),
            Triple("Charges", "charges", false),
        )
        specs.chunked(2).forEach { pair ->
            val row = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            pair.forEachIndexed { i, (label, key, upIsGood) ->
                val tile = tile(label, totals.optDouble(key, 0.0), change.opt(key) as? Number, upIsGood)
                row.addView(tile, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                    if (i == 0) marginEnd = dp(6) else marginStart = dp(6)
                })
            }
            grid.addView(row, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                topMargin = dp(12)
            })
        }
        return grid
    }

    private fun tile(label: String, amount: Double, change: Number?, upIsGood: Boolean): View {
        val body = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        body.addView(caption(label))
        body.addView(TextView(ctx).apply {
            text = Money.format(amount, currency, prefs.hideAmounts)
            textSize = 17f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(color(R.color.ink))
            setPadding(0, dp(4), 0, dp(2))
        })
        body.addView(TextView(ctx).apply {
            textSize = 12f
            if (change == null) {
                text = "No data last month"
                setTextColor(color(R.color.muted))
            } else {
                val pct = change.toDouble()
                val good = if (pct >= 0) upIsGood else !upIsGood
                val arrow = if (pct > 0) "▲" else if (pct < 0) "▼" else "■"
                text = "$arrow ${"%.0f".format(Locale.US, kotlin.math.abs(pct))}% vs last month"
                setTextColor(color(if (pct == 0.0) R.color.muted else if (good) R.color.money_in else R.color.money_out))
            }
        })
        return card(body, top = 0)
    }

    private fun stats(stats: JSONObject): View {
        val box = section("At a glance")
        val hidden = prefs.hideAmounts
        box.addView(pair("Average spent a day", Money.format(stats.optDouble("average_daily_out", 0.0), currency, hidden)))
        box.addView(pair("Kept of what came in", percent(stats.opt("savings_rate"))))
        box.addView(pair("Charges as a share of spending", percent(stats.opt("charges_share"))))
        box.addView(pair("Transactions", stats.optInt("transactions", 0).toString()))
        return card(box)
    }

    private fun trend(rows: JSONArray): View {
        val box = section("Last 6 months")
        val parse = SimpleDateFormat("yyyy-MM", Locale.US)
        val label = SimpleDateFormat("MMM", Locale.getDefault())
        val months = (0 until rows.length()).map {
            val m = rows.getJSONObject(it)
            val name = runCatching { label.format(parse.parse(m.optString("month"))!!) }.getOrDefault("")
            BarChartView.Day(name, m.optDouble("in", 0.0), m.optDouble("out", 0.0))
        }
        box.addView(BarChartView(ctx).apply { setDays(months) },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(170)).apply { topMargin = dp(8) })
        box.addView(legend(listOf("In" to color(R.color.money_in), "Out" to color(R.color.money_out))))
        return card(box)
    }

    private fun categories(rows: JSONArray, spent: Double): View {
        val box = section("Where the money went")
        if (rows.length() == 0) {
            box.addView(muted("No spending recorded this month"))
            return card(box)
        }
        val slices = (0 until rows.length()).map {
            val r = rows.getJSONObject(it)
            DonutChartView.Slice(r.optString("label"), r.optDouble("amount", 0.0), palette[it % palette.size])
        }
        val centre = if (prefs.hideAmounts) "•••" else Money.short(spent)
        box.addView(DonutChartView(ctx).apply { setSlices(slices, centre, "spent") },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(8) })
        val total = slices.sumOf { it.value }.coerceAtLeast(1.0)
        slices.forEach { s ->
            val share = "%.0f%%".format(Locale.US, s.value * 100 / total)
            box.addView(pair(s.label, "${Money.format(s.value, currency, prefs.hideAmounts)}  ·  $share", dot = s.color))
        }
        return card(box)
    }

    /** Each line with a bar showing its share of the biggest one. */
    private fun ranking(title: String, rows: JSONArray, barColor: Int, empty: String): View {
        val box = section(title)
        val top = (0 until rows.length()).maxOfOrNull { rows.getJSONObject(it).optDouble("amount", 0.0) } ?: 0.0
        if (top <= 0) {
            box.addView(muted(empty))
            return card(box)
        }
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val amount = row.optDouble("amount", 0.0)
            box.addView(pair(row.optString("label"), Money.format(amount, currency, prefs.hideAmounts)))
            box.addView(LinearProgressIndicator(ctx).apply {
                max = 100
                progress = ((amount / top) * 100).toInt().coerceIn(if (amount > 0) 2 else 0, 100)
                setIndicatorColor(color(barColor))
                trackCornerRadius = dp(4)
                trackThickness = dp(6)
            })
        }
        return card(box)
    }

    private fun biggest(rows: JSONArray): View {
        val box = section("Biggest payments")
        if (rows.length() == 0) box.addView(muted("No payments this month"))
        val parse = SimpleDateFormat("yyyy-MM-dd", Locale.US)
        val show = SimpleDateFormat("d MMM", Locale.getDefault())
        for (i in 0 until rows.length()) {
            val r = rows.getJSONObject(i)
            val day = runCatching { show.format(parse.parse(r.optString("date"))!!) }.getOrDefault("")
            box.addView(pair("${r.optString("label").ifEmpty { "Payment" }}\n$day",
                Money.format(r.optDouble("amount", 0.0), currency, prefs.hideAmounts)))
        }
        return card(box)
    }

    // ── Building blocks ──────────────────────────────────────────────────────

    private fun section(title: String): LinearLayout = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        addView(caption(title))
    }

    private fun card(body: View, top: Int = 12): View = MaterialCardView(ctx).apply {
        radius = dp(16).toFloat()
        cardElevation = dp(1).toFloat()
        setCardBackgroundColor(color(R.color.card))
        strokeWidth = 0
        setContentPadding(dp(16), dp(14), dp(16), dp(14))
        addView(body)
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(top)
        }
    }

    private fun caption(text: String) = TextView(ctx).apply {
        this.text = text.uppercase(Locale.getDefault())
        textSize = 12f
        letterSpacing = 0.05f
        setTextColor(color(R.color.muted))
    }

    private fun pair(left: String, right: String, dot: Int? = null): View = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(0, dp(8), 0, dp(4))
        if (dot != null) {
            addView(View(ctx).apply {
                background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(dot) }
            }, LinearLayout.LayoutParams(dp(10), dp(10)).apply { marginEnd = dp(8) })
        }
        addView(TextView(ctx).apply { text = left; textSize = 14f; setTextColor(color(R.color.ink)) },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        addView(TextView(ctx).apply {
            text = right
            textSize = 14f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(color(R.color.ink))
        })
    }

    private fun legend(items: List<Pair<String, Int>>): View = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        setPadding(0, dp(6), 0, 0)
        items.forEach { (name, c) ->
            addView(View(ctx).apply {
                background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(c) }
            }, LinearLayout.LayoutParams(dp(8), dp(8)).apply { marginEnd = dp(6); gravity = Gravity.CENTER_VERTICAL })
            addView(TextView(ctx).apply { text = name; textSize = 12f; setTextColor(color(R.color.muted)) },
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginEnd = dp(16) })
        }
    }

    private fun arrow(symbol: String, description: String, onClick: () -> Unit): View =
        MaterialButton(ctx, null, com.google.android.material.R.attr.materialIconButtonStyle).apply {
            text = symbol
            textSize = 22f
            contentDescription = description
            setTextColor(color(R.color.ink))
            setOnClickListener { onClick() }
        }

    private fun muted(message: String) = TextView(ctx).apply {
        text = message
        setTextColor(color(R.color.muted))
        setPadding(0, dp(12), 0, 0)
    }

    private fun percent(value: Any?): String = (value as? Number)?.let { "%.0f%%".format(Locale.US, it.toDouble()) } ?: "—"

    private fun shiftMonth(by: Int) {
        val next = (month.clone() as Calendar).apply { add(Calendar.MONTH, by) }
        if (next.after(Calendar.getInstance())) return
        month.time = next.time
        load()
    }

    private fun monthKey() = SimpleDateFormat("yyyy-MM", Locale.US).format(month.time)
    private fun isCurrentMonth() = monthKey() == SimpleDateFormat("yyyy-MM", Locale.US).format(Date())
    private fun color(id: Int) = ContextCompat.getColor(ctx, id)
    private fun dp(v: Int) = (v * ctx.resources.displayMetrics.density).toInt()
}
