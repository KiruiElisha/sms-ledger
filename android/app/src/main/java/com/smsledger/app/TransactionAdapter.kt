package com.smsledger.app

import android.graphics.drawable.GradientDrawable
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONObject

/** One SMS Transaction per row: who, when, how much, and what ERPNext made of it. */
class TransactionAdapter(private val onClick: (JSONObject) -> Unit) : RecyclerView.Adapter<TransactionAdapter.Row>() {

    val items = mutableListOf<JSONObject>()

    class Row(view: View) : RecyclerView.ViewHolder(view) {
        val avatar: TextView = view.findViewById(R.id.avatar)
        val title: TextView = view.findViewById(R.id.title)
        val subtitle: TextView = view.findViewById(R.id.subtitle)
        val amount: TextView = view.findViewById(R.id.amount)
        val status: TextView = view.findViewById(R.id.status)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        Row(LayoutInflater.from(parent.context).inflate(R.layout.item_transaction, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(row: Row, position: Int) {
        val t = items[position]
        val ctx = row.itemView.context
        val title = Transactions.title(t)
        row.title.text = title
        row.subtitle.text = Transactions.subtitle(t)
        row.amount.text = Transactions.signedAmount(t)
        row.amount.setTextColor(ContextCompat.getColor(ctx, Transactions.amountColor(t)))
        row.status.text = t.optString("status")
        row.status.setTextColor(ContextCompat.getColor(ctx, Transactions.statusColor(t)))
        row.avatar.text = title.firstOrNull { it.isLetterOrDigit() }?.uppercase() ?: "?"
        row.avatar.background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Transactions.avatarColor(title))
        }
        row.itemView.setOnClickListener { onClick(t) }
    }
}
