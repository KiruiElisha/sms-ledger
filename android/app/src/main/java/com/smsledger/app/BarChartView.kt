package com.smsledger.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat

/** Money in and out per day, as pairs of bars. Drawn by hand to keep the APK small. */
class BarChartView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {

    data class Day(val label: String, val moneyIn: Double, val moneyOut: Double)

    private var days: List<Day> = emptyList()
    private val density = resources.displayMetrics.density
    private val inPaint = paint(R.color.money_in)
    private val outPaint = paint(R.color.money_out)
    private val gridPaint = paint(R.color.chart_grid).apply { strokeWidth = density }
    private val labelPaint = paint(R.color.muted).apply {
        textSize = 10 * resources.displayMetrics.scaledDensity
        textAlign = Paint.Align.CENTER
    }
    private val bar = RectF()

    fun setDays(value: List<Day>) {
        days = value
        contentDescription = value.joinToString { "${it.label}: in ${Money.short(it.moneyIn)}, out ${Money.short(it.moneyOut)}" }
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (days.isEmpty()) return
        val labelSpace = labelPaint.textSize + 6 * density
        val chartBottom = height - labelSpace
        val top = labelPaint.textSize + 4 * density
        val peak = days.maxOf { maxOf(it.moneyIn, it.moneyOut) }.coerceAtLeast(1.0)
        canvas.drawLine(0f, chartBottom, width.toFloat(), chartBottom, gridPaint)
        canvas.drawText(Money.short(peak), labelPaint.measureText("0000") / 2, labelPaint.textSize, labelPaint)

        val slot = width / days.size.toFloat()
        val barWidth = (slot - 4 * density) / 2
        days.forEachIndexed { i, day ->
            val left = i * slot + 2 * density
            drawBar(canvas, left, barWidth, day.moneyIn, peak, top, chartBottom, inPaint)
            drawBar(canvas, left + barWidth, barWidth, day.moneyOut, peak, top, chartBottom, outPaint)
            if (i % 2 == days.size % 2 || days.size <= 7) {
                canvas.drawText(day.label, left + barWidth, height - 2 * density, labelPaint)
            }
        }
    }

    private fun drawBar(canvas: Canvas, left: Float, w: Float, value: Double, peak: Double, top: Float, bottom: Float, p: Paint) {
        if (value <= 0) return
        val h = ((bottom - top) * (value / peak)).toFloat().coerceAtLeast(2 * density)
        bar.set(left, bottom - h, left + w - density, bottom)
        canvas.drawRoundRect(bar, 2 * density, 2 * density, p)
    }

    private fun paint(color: Int) = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = ContextCompat.getColor(context, color) }
}
