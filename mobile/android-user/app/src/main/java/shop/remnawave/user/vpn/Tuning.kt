package shop.remnawave.user.vpn

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/**
 * Stage 19, C3: the customer's own routing rules and TLS fragmentation for the embedded VPN — the same ideas as in
 * «Корги Люси: клиент» (mobile/android-client), written for this app's configs (share links and Remnawave JSON).
 *
 * A rule sends a domain or an address through the VPN, around it, or nowhere. This app carries no geoip.dat /
 * geosite.dat, so geo rules are refused when typed (Xray would reject the whole config with them).
 */
data class RouteRule(val match: String, val action: String) {
    init { require(action in ACTIONS) { "action" } }

    val isIp: Boolean get() = IP.matches(match)

    fun toJson(): JSONObject = JSONObject().put("match", match).put("action", action)

    companion object {
        val ACTIONS = listOf("proxy", "direct", "block")
        private val IP = Regex("^[0-9a-fA-F:.]+(/\\d{1,3})?$")
        private val PREFIXES = listOf("domain:", "full:", "regexp:", "keyword:")

        /** What the customer typed: «example.com», «full:api.example.com», «keyword:ads», «10.0.0.0/8». */
        fun normalize(raw: String): String {
            val value = raw.trim().lowercase()
            require(value.isNotBlank() && value.length <= 200 && value.none { it.isWhitespace() }) { "empty" }
            require(!value.startsWith("geoip:") && !value.startsWith("geosite:") && !value.startsWith("ext:")) { "geo" }
            if (value.startsWith("regexp:")) runCatching { Regex(value.removePrefix("regexp:")) }.getOrElse { throw IllegalArgumentException("regexp") }
            return when {
                PREFIXES.any { value.startsWith(it) } -> value.also { require(it.substringAfter(':').isNotBlank()) { "empty" } }
                IP.matches(value) -> value
                else -> "domain:${value.removePrefix("https://").removePrefix("http://").substringBefore('/')}"
            }
        }

        fun of(json: JSONObject) = RouteRule(json.getString("match"), json.getString("action"))
    }
}

data class Tuning(
    val rules: List<RouteRule> = emptyList(),
    val fragment: Boolean = false,
    val fragmentPackets: String = "tlshello",
) {
    init {
        require(rules.size <= MAX_RULES) { "rules" }
        require(fragmentPackets in PACKETS) { "packets" }
    }

    fun toJson(): JSONObject = JSONObject().put("rules", JSONArray(rules.map { it.toJson() }))
        .put("fragment", fragment).put("fragmentPackets", fragmentPackets)

    /** A new rule replaces an older one for the same match. */
    fun withRule(rule: RouteRule): Tuning = copy(rules = rules.filter { it.match != rule.match } + rule)

    fun without(match: String): Tuning = copy(rules = rules.filter { it.match != match })

    /**
     * Rules and fragmentation put into a finished Xray config (from share links or from a Remnawave JSON config).
     * ``leading`` — how many rules at the top this app put there itself (private ranges, Russian sites): the customer's
     * rules go right after them and before every other rule, so they win over the subscription's own routing.
     */
    fun apply(config: JSONObject, leading: Int): JSONObject {
        val outbounds = config.optJSONArray("outbounds") ?: JSONArray().also { config.put("outbounds", it) }
        if (fragment) {
            for (i in 0 until outbounds.length()) {
                val stream = outbounds.optJSONObject(i)?.optJSONObject("streamSettings") ?: continue
                // Only TLS: REALITY imitates another site's handshake and is not split; plain connections have no ClientHello.
                if (stream.optString("security") != "tls") continue
                val sockopt = stream.optJSONObject("sockopt") ?: JSONObject().also { stream.put("sockopt", it) }
                if (!sockopt.has("dialerProxy")) sockopt.put("dialerProxy", FRAGMENT)
            }
            if (tags(outbounds).none { it == FRAGMENT }) outbounds.put(JSONObject().put("tag", FRAGMENT).put("protocol", "freedom")
                .put("settings", JSONObject().put("fragment", JSONObject().put("packets", fragmentPackets).put("length", LENGTH).put("interval", INTERVAL))))
        }
        if (rules.isEmpty()) return config
        val routing = config.optJSONObject("routing") ?: JSONObject().also { config.put("routing", it) }
        val old = routing.optJSONArray("rules") ?: JSONArray()
        val proxy = proxyTarget(routing, outbounds)
        val direct = ensure(outbounds, "freedom")
        val block = ensure(outbounds, "blackhole")
        val mine = rules.map { rule ->
            val row = JSONObject().put("type", "field").put(if (rule.isIp) "ip" else "domain", JSONArray().put(rule.match))
            when (rule.action) {
                "direct" -> row.put("outboundTag", direct)
                "block" -> row.put("outboundTag", block)
                else -> row.put(proxy.first, proxy.second)
            }
        }
        val merged = JSONArray()
        for (i in 0 until minOf(leading, old.length())) merged.put(old.get(i))
        mine.forEach { merged.put(it) }
        for (i in leading until old.length()) merged.put(old.get(i))
        routing.put("rules", merged)
        return config
    }

    companion object {
        const val PREF = "vpn_tuning"
        const val MAX_RULES = 200
        const val FRAGMENT = "corgi-fragment"
        const val LENGTH = "100-200"
        const val INTERVAL = "10-20"
        val PACKETS = listOf("tlshello", "1-3", "1-5")

        fun of(json: JSONObject) = Tuning(
            json.optJSONArray("rules")?.let { a -> (0 until a.length()).mapNotNull { runCatching { RouteRule.of(a.getJSONObject(it)) }.getOrNull() } }
                ?.take(MAX_RULES) ?: emptyList(),
            json.optBoolean("fragment", false),
            json.optString("fragmentPackets", "tlshello").takeIf { it in PACKETS } ?: "tlshello",
        )

        fun load(prefs: SharedPreferences): Tuning = prefs.getString(PREF, null)?.let { runCatching { of(JSONObject(it)) }.getOrNull() } ?: Tuning()

        fun save(prefs: SharedPreferences, tuning: Tuning) = prefs.edit().putString(PREF, tuning.toJson().toString()).apply()

        private fun isService(outbounds: JSONArray, tag: String): Boolean = (0 until outbounds.length()).any {
            val row = outbounds.optJSONObject(it)
            row?.optString("tag") == tag && row.optString("protocol") in setOf("freedom", "blackhole", "dns", "loopback")
        }

        private fun tags(outbounds: JSONArray): List<String> = (0 until outbounds.length()).mapNotNull { outbounds.optJSONObject(it)?.optString("tag") }

        /** The tag of an outbound of this protocol (direct = freedom without fragmentation, block = blackhole), added if missing. */
        private fun ensure(outbounds: JSONArray, protocol: String): String {
            for (i in 0 until outbounds.length()) {
                val row = outbounds.optJSONObject(i) ?: continue
                if (row.optString("protocol") == protocol && row.optString("tag") != FRAGMENT && row.optString("tag").isNotBlank()
                    && row.optJSONObject("settings")?.has("fragment") != true) return row.getString("tag")
            }
            val tag = if (protocol == "freedom") "corgi-direct" else "corgi-block"
            outbounds.put(JSONObject().put("tag", tag).put("protocol", protocol))
            return tag
        }

        /**
         * Where «через VPN» goes: where the catch-all rule sends everything else (the chosen server or the automatic
         * choice), else the subscription's balancer, else its first proxy outbound.
         */
        private fun proxyTarget(routing: JSONObject, outbounds: JSONArray): Pair<String, String> {
            val rules = routing.optJSONArray("rules") ?: JSONArray()
            for (i in rules.length() - 1 downTo 0) {
                val rule = rules.optJSONObject(i) ?: continue
                if (listOf("domain", "ip", "port", "source", "protocol", "inboundTag", "user", "attrs").any { rule.has(it) }) continue
                for (key in listOf("balancerTag", "outboundTag")) {
                    val tag = rule.optString(key)
                    if (tag.isNotBlank() && tag !in tags(outbounds).filter { t -> isService(outbounds, t) }) return key to tag
                }
            }
            routing.optJSONArray("balancers")?.optJSONObject(0)?.optString("tag")?.takeIf { it.isNotBlank() }?.let { return "balancerTag" to it }
            for (i in 0 until outbounds.length()) {
                val row = outbounds.optJSONObject(i) ?: continue
                if (row.optString("protocol") !in setOf("freedom", "blackhole", "dns", "loopback") && row.optString("tag").isNotBlank()) return "outboundTag" to row.getString("tag")
            }
            throw IllegalStateException("no servers")
        }
    }
}
