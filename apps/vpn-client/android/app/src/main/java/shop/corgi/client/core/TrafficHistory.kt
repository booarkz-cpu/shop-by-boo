package shop.corgi.client.core

import org.json.JSONObject

/**
 * v1.7.3 (N12, phase 2): traffic by day — what went through the VPN (proxy outbounds) and what went direct (the
 * «direct» outbound: local network, Russian sites in «РФ напрямую», own «direct» rules). Kept for [KEEP_DAYS] days as
 * JSON in the app's preferences: {"2026-11-08": [vpn, direct], …}.
 */
object TrafficHistory {
    const val KEEP_DAYS = 90

    data class Day(val day: String, val vpn: Long, val direct: Long)

    private val DAY = Regex("^\\d{4}-\\d{2}-\\d{2}$")

    fun day(millis: Long, zone: java.util.TimeZone = java.util.TimeZone.getDefault()): String =
        java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.ROOT).apply { timeZone = zone }.format(java.util.Date(millis))

    /** [json] with [vpn] and [direct] bytes added to [day]; days older than [KEEP_DAYS] before it are dropped. */
    fun add(json: String, day: String, vpn: Long, direct: Long): String {
        require(DAY.matches(day)) { "day" }
        val all = read(json).associateBy { it.day }.toMutableMap()
        val old = all[day] ?: Day(day, 0, 0)
        all[day] = Day(day, old.vpn + vpn.coerceAtLeast(0), old.direct + direct.coerceAtLeast(0))
        val kept = all.values.sortedBy { it.day }.takeLast(KEEP_DAYS)
        return JSONObject().apply { kept.forEach { put(it.day, org.json.JSONArray().put(it.vpn).put(it.direct)) } }.toString()
    }

    fun read(json: String): List<Day> {
        val obj = runCatching { JSONObject(json) }.getOrNull() ?: return emptyList()
        return obj.keys().asSequence().filter { DAY.matches(it) }.mapNotNull { key ->
            val a = obj.optJSONArray(key) ?: return@mapNotNull null
            Day(key, a.optLong(0), a.optLong(1))
        }.sortedBy { it.day }.toList()
    }

    /** The last [days] days up to [today] in order, a day without traffic as zeros (for the chart). */
    fun series(json: String, days: Int, today: Long): List<Day> {
        val known = read(json).associateBy { it.day }
        return (days - 1 downTo 0).map { back ->
            val d = day(today - back * 86_400_000L)
            known[d] ?: Day(d, 0, 0)
        }
    }
}
