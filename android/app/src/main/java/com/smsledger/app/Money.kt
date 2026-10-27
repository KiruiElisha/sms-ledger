package com.smsledger.app

import java.text.NumberFormat
import java.util.Locale

object Money {
    private val number = NumberFormat.getNumberInstance(Locale.US).apply {
        minimumFractionDigits = 2
        maximumFractionDigits = 2
    }

    fun format(amount: Double, currency: String = "KES", hidden: Boolean = false): String =
        if (hidden) "$currency •••" else "$currency ${number.format(amount)}"

    /** "KES 12.5K" for chart labels and tight spots. */
    fun short(amount: Double): String = when {
        amount >= 1_000_000 -> "%.1fM".format(Locale.US, amount / 1_000_000)
        amount >= 1_000 -> "%.1fK".format(Locale.US, amount / 1_000)
        else -> "%.0f".format(Locale.US, amount)
    }
}
