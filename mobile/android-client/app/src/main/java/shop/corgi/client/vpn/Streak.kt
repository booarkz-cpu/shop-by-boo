package shop.corgi.client.vpn

import android.content.Context
import java.time.LocalDate

/**
 * v1.5.0: «Стрик» on the main screen — how many days in a row the VPN was on. Counted on the phone only (the days are
 * kept in the app's preferences, nothing leaves the device); a day without a connection ends the streak.
 */
object Streak {
    private const val KEY = "streak_days"
    private const val KEEP = 400

    /** Consecutive days ending today (or yesterday, when today has no connection yet). */
    fun count(days: Set<LocalDate>, today: LocalDate): Int {
        var day = if (today in days) today else today.minusDays(1)
        var n = 0
        while (day in days) {
            n++
            day = day.minusDays(1)
        }
        return n
    }

    /** The days with a connection, today added; only the last [KEEP] days are kept. */
    fun with(days: Set<LocalDate>, today: LocalDate): Set<LocalDate> =
        (days + today).filter { !it.isBefore(today.minusDays(KEEP.toLong())) }.toSet()

    fun days(context: Context): Set<LocalDate> =
        prefs(context).getStringSet(KEY, emptySet()).orEmpty().mapNotNull { runCatching { LocalDate.parse(it) }.getOrNull() }.toSet()

    fun record(context: Context, today: LocalDate = LocalDate.now()) {
        prefs(context).edit().putStringSet(KEY, with(days(context), today).map { it.toString() }.toSet()).apply()
    }

    fun current(context: Context, today: LocalDate = LocalDate.now()): Int = count(days(context), today)

    private fun prefs(context: Context) = context.getSharedPreferences("client_streak", 0)
}
