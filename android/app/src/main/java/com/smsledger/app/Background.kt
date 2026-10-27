package com.smsledger.app

import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executors

/** Network calls off the main thread, results back on it. */
object Background {
    private val pool = Executors.newFixedThreadPool(2)
    private val main = Handler(Looper.getMainLooper())

    fun <T> run(work: () -> T, done: (Result<T>) -> Unit) {
        pool.execute {
            val result = runCatching(work)
            main.post { done(result) }
        }
    }
}
