package com.smsledger.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat

/** Shares of a whole as a ring, with the total in the middle. Drawn by hand to keep the APK small. */
class DonutChartView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {

    data class Slice(val label: String, val value: Double, val color: Int)

    private var slices: List<Slice> = emptyList()
    private var centre = ""
    private var caption = ""
    private val density = resources.displayMetrics.density
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 22 * density
    }
    private val track = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 22 * density
        color = ContextCompat.getColor(context, R.color.chart_grid)
    }
    private val big = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        textSize = 18 * resources.displayMetrics.scaledDensity
        isFakeBoldText = true
        color = ContextCompat.getColor(context, R.color.ink)
    }
    private val small = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        textSize = 11 * resources.displayMetrics.scaledDensity
        color = ContextCompat.getColor(context, R.color.muted)
    }
    private val box = RectF()

    fun setSlices(value: List<Slice>, centreText: String, captionText: String) {
        slices = value.filter { it.value > 0 }
        centre = centreText
        caption = captionText
        contentDescription = "$captionText $centreText: " + slices.joinToString { "${it.label} ${Money.short(it.value)}" }
        invalidate()
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val width = MeasureSpec.getSize(widthMeasureSpec)
        setMeasuredDimension(width, minOf(width, (190 * density).toInt()))
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = minOf(width, height) - ring.strokeWidth
        val left = (width - size) / 2f
        val top = (height - size) / 2f
        box.set(left, top, left + size, top + size)
        canvas.drawArc(box, 0f, 360f, false, track)
        val total = slices.sumOf { it.value }
        if (total > 0) {
            var start = -90f
            slices.forEach { slice ->
                val sweep = (360.0 * slice.value / total).toFloat()
                ring.color = slice.color
                canvas.drawArc(box, start, (sweep - 1.5f).coerceAtLeast(0.5f), false, ring)
                start += sweep
            }
        }
        val middle = height / 2f
        canvas.drawText(centre, width / 2f, middle + big.textSize / 3, big)
        canvas.drawText(caption, width / 2f, middle + big.textSize / 3 + small.textSize + 4 * density, small)
    }
}
