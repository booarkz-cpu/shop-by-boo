package shop.corgi.client.core

/**
 * v1.9.9: a subscription that fails to update is not asked again at every background run. After a failure the next
 * automatic try waits 15 minutes, then 30, then an hour… up to 6 hours; the first success clears it. «Обновить» by
 * hand is never delayed.
 */
object Backoff {
    const val FIRST_MS = 15 * 60_000L
    const val MAX_MS = 6 * 3_600_000L

    /** How long to wait after the [failures]-th failure in a row. */
    fun delay(failures: Int): Long = if (failures <= 0) 0L else minOf(MAX_MS, FIRST_MS shl minOf(failures - 1, 16))

    /** Whether the background update may ask the server now. */
    fun due(now: Long, updatedAt: Long, triedAt: Long, failures: Int, intervalMs: Long): Boolean =
        now - updatedAt >= intervalMs && (failures <= 0 || now - triedAt >= delay(failures))

    /** When the background update asks next (for the «следующее обновление» line). */
    fun next(updatedAt: Long, triedAt: Long, failures: Int, intervalMs: Long): Long =
        maxOf(updatedAt + intervalMs, if (failures > 0) triedAt + delay(failures) else 0L)
}
