package com.smsledger.app

import android.app.Activity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.DividerItemDecoration
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import org.json.JSONObject

/** Every message sent to ERPNext, newest first, filtered by what happened to it. */
class ActivityScreen(parent: ViewGroup, private val activity: Activity, private val prefs: Prefs) {
    val view: View = LayoutInflater.from(parent.context).inflate(R.layout.screen_activity, parent, false)
    private val refresh = view.findViewById<SwipeRefreshLayout>(R.id.refresh)
    private val empty = view.findViewById<TextView>(R.id.empty)
    private val sheet = TransactionSheet(activity, prefs) { updated -> replace(updated) }
    private val adapter = TransactionAdapter { sheet.show(it) }
    private val chips = view.findViewById<ChipGroup>(R.id.filters)
    private var status: String? = null
    private var loading = false
    private var exhausted = false
    private var generation = 0  // a reload makes any page still on its way stale

    init {
        val list = view.findViewById<RecyclerView>(R.id.list)
        val layout = LinearLayoutManager(activity)
        list.layoutManager = layout
        list.adapter = adapter
        list.addItemDecoration(DividerItemDecoration(activity, DividerItemDecoration.VERTICAL))
        list.addOnScrollListener(object : RecyclerView.OnScrollListener() {
            override fun onScrolled(rv: RecyclerView, dx: Int, dy: Int) {
                if (dy > 0 && layout.findLastVisibleItemPosition() >= adapter.itemCount - 5) loadMore()
            }
        })
        refresh.setOnRefreshListener { reload() }
        FILTERS.forEach { (label, value) ->
            chips.addView(Chip(activity).apply {
                text = label
                isCheckable = true
                isChecked = value == null
                setOnClickListener { status = value; reload() }
            })
        }
    }

    /** Opens on the messages that need fixing, as the home screen's banner asks. */
    fun showAttention() {
        status = "attention"
        (chips.getChildAt(FILTERS.indexOfFirst { it.second == "attention" }) as Chip).isChecked = true
        reload()
    }

    fun reload() {
        generation++
        loading = false
        exhausted = false
        adapter.items.clear()
        adapter.notifyDataSetChanged()
        loadMore()
    }

    private fun loadMore() {
        if (loading || exhausted) return
        if (!prefs.isConfigured) {
            refresh.isRefreshing = false
            return showEmpty("Connect to ERPNext under Settings first.")
        }
        loading = true
        refresh.isRefreshing = true
        val start = adapter.items.size
        val wanted = status
        val asked = generation
        Background.run({ ErpClient(prefs).activity(start, wanted) }) { result ->
            if (asked != generation) return@run
            loading = false
            refresh.isRefreshing = false
            result.onSuccess { page ->
                exhausted = page.length() < ErpClient.PAGE
                val from = adapter.items.size
                for (i in 0 until page.length()) adapter.items.add(page.getJSONObject(i))
                adapter.notifyItemRangeInserted(from, page.length())
                showEmpty(if (adapter.items.isEmpty()) "Nothing here yet." else null)
            }.onFailure { showEmpty(it.message ?: "Could not reach ERPNext") }
        }
    }

    private fun replace(updated: JSONObject) {
        val i = adapter.items.indexOfFirst { it.optString("name") == updated.optString("name") }
        if (i < 0) return
        adapter.items[i] = updated
        adapter.notifyItemChanged(i)
    }

    private fun showEmpty(message: String?) {
        empty.visibility = if (message == null) View.GONE else View.VISIBLE
        empty.text = message
    }

    companion object {
        private val FILTERS = listOf(
            "All" to null,
            "Needs attention" to "attention",
            "Posted" to "Posted",
            "Linked" to "Linked",
            "Ignored" to "Ignored",
        )
    }
}
