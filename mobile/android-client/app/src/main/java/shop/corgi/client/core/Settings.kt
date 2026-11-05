package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject

/** One routing rule: what matches (domain:, full:, regexp:, keyword:, geosite:, geoip:, an IP or CIDR) and where it goes. */
data class Rule(val match: String, val action: String) {
    init { require(action in ACTIONS) { "action" } }

    val isIp: Boolean get() = match.startsWith("geoip:") || IP.matches(match)

    fun toJson(): JSONObject = JSONObject().put("match", match).put("action", action)

    companion object {
        val ACTIONS = listOf("proxy", "direct", "block")
        private val IP = Regex("^[0-9a-fA-F:.]+(/\\d{1,3})?$")
        fun of(json: JSONObject) = Rule(json.getString("match"), json.getString("action"))

        /** A line typed by the user: «example.com», «domain:example.com», «geosite:category-ads-all», «10.0.0.0/8». */
        fun normalize(raw: String): String {
            val value = raw.trim().lowercase()
            require(value.isNotBlank() && value.length <= 200 && !value.contains(' ')) { "empty" }
            return when {
                listOf("domain:", "full:", "regexp:", "keyword:", "geosite:", "geoip:").any { value.startsWith(it) } -> value
                IP.matches(value) -> value
                else -> "domain:$value"
            }
        }
    }
}

/** Everything the user set; stored as JSON. Defaults are what a new install uses. */
data class Settings(
    val routing: String = "bypass_lan",          // global | bypass_lan | bypass_ru | custom
    val rules: List<Rule> = emptyList(),
    val dns: List<String> = listOf("1.1.1.1", "8.8.8.8"),
    val fragment: Boolean = false,
    val fragmentLength: String = "100-200",
    val fragmentInterval: String = "10-20",
    val appsMode: String = "all",                // all | only | except
    val apps: Set<String> = emptySet(),
    val mtu: Int = 1500,
    val ipv6: Boolean = true,
    val theme: String = "system",                // system | dark | light
    val geoipUrl: String = DEFAULT_GEOIP,
    val geositeUrl: String = DEFAULT_GEOSITE,
) {
    init {
        require(routing in ROUTING) { "routing" }
        require(appsMode in listOf("all", "only", "except")) { "apps" }
        require(mtu in 1280..9000) { "mtu" }
        require(RANGE.matches(fragmentLength) && RANGE.matches(fragmentInterval)) { "fragment" }
    }

    fun toJson(): JSONObject = JSONObject().put("routing", routing).put("rules", JSONArray(rules.map { it.toJson() }))
        .put("dns", JSONArray(dns)).put("fragment", fragment).put("fragmentLength", fragmentLength).put("fragmentInterval", fragmentInterval)
        .put("appsMode", appsMode).put("apps", JSONArray(apps.sorted())).put("mtu", mtu).put("ipv6", ipv6).put("theme", theme)
        .put("geoipUrl", geoipUrl).put("geositeUrl", geositeUrl)

    companion object {
        val ROUTING = listOf("global", "bypass_lan", "bypass_ru", "custom")
        private val RANGE = Regex("^\\d{1,4}(-\\d{1,4})?$")
        // runetfreedom/russia-v2ray-rules-dat (GPL-3.0 data files, downloaded by the user's choice, not bundled).
        const val DEFAULT_GEOIP = "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geoip.dat"
        const val DEFAULT_GEOSITE = "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geosite.dat"

        fun of(json: JSONObject?): Settings {
            if (json == null) return Settings()
            val d = Settings()
            fun strings(key: String, fallback: List<String>) = json.optJSONArray(key)?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: fallback
            return runCatching {
                Settings(json.optString("routing", d.routing),
                    json.optJSONArray("rules")?.let { a -> (0 until a.length()).map { Rule.of(a.getJSONObject(it)) } } ?: d.rules,
                    strings("dns", d.dns), json.optBoolean("fragment", d.fragment), json.optString("fragmentLength", d.fragmentLength),
                    json.optString("fragmentInterval", d.fragmentInterval), json.optString("appsMode", d.appsMode), strings("apps", emptyList()).toSet(),
                    json.optInt("mtu", d.mtu), json.optBoolean("ipv6", d.ipv6), json.optString("theme", d.theme),
                    json.optString("geoipUrl", d.geoipUrl), json.optString("geositeUrl", d.geositeUrl))
            }.getOrDefault(d)
        }
    }
}
