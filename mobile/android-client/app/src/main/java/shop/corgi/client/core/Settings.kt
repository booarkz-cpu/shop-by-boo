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

/** v1.4.0: a named set of routing — the mode and the rules — to switch between in one tap («Профили маршрутизации»). */
data class RoutingProfile(val name: String, val routing: String, val rules: List<Rule>) {
    init { require(name.isNotBlank() && name.length <= 40) { "name" }; require(routing in Settings.ROUTING) { "routing" } }

    fun toJson(): JSONObject = JSONObject().put("name", name).put("routing", routing).put("rules", JSONArray(rules.map { it.toJson() }))

    companion object {
        fun of(j: JSONObject) = RoutingProfile(j.getString("name"), j.getString("routing"),
            j.optJSONArray("rules")?.let { a -> (0 until a.length()).map { Rule.of(a.getJSONObject(it)) } } ?: emptyList())
    }
}

/**
 * Everything the user set; stored as JSON. Defaults are what a new install uses. Every field here is shown in the
 * settings menu and changes what the app does (no switches without an effect).
 */
data class Settings(
    // Routing
    val routing: String = "bypass_lan",          // global | bypass_lan | bypass_ru | custom
    val rules: List<Rule> = emptyList(),
    val geoipUrl: String = DEFAULT_GEOIP,
    val geositeUrl: String = DEFAULT_GEOSITE,
    // Tunnel
    val dns: List<String> = listOf("1.1.1.1", "8.8.8.8"),
    val fragment: Boolean = false,
    val fragmentPackets: String = "tlshello",    // tlshello | 1-3 | 1-5
    val fragmentLength: String = "100-200",
    val fragmentInterval: String = "10-20",
    val mtu: Int = 1500,
    val ipv6: Boolean = true,
    val sniffing: Boolean = true,
    val routeOnly: Boolean = true,
    val blockUdp: Boolean = false,
    val idleTimeout: Int = 300,                  // seconds (Xray policy connIdle)
    val excludedRoutes: List<String> = emptyList(),
    // v1.4.0: «TUN + прокси» or «только прокси» (no VPN icon), the local SOCKS5/HTTP proxy and sharing it to the LAN
    val tunnelMode: String = "tun",              // tun | proxy
    val localProxy: Boolean = false,             // in «tun» mode: SOCKS5/HTTP on the device too
    val shareLan: Boolean = false,               // bind 0.0.0.0: devices of the same Wi-Fi / hotspot use the phone
    val socksPort: Int = 10808,
    val httpPort: Int = 10809,
    val proxyAuth: Boolean = true,               // SOCKS5 login and password
    val httpAuth: Boolean = true,                // the same login and password on the HTTP proxy
    val proxyUser: String = "",
    val proxyPass: String = "",
    val mux: Boolean = false,
    val muxConcurrency: Int = 8,
    val noises: Boolean = false,
    val speedNotification: Boolean = true,
    val wakelock: Boolean = false,
    val autoConnectLaunch: Boolean = false,
    val autoConnectBoot: Boolean = false,
    val tileDetails: Boolean = true,             // the tile shows the server and the state, not only the name
    val logLevel: String = "none",               // none | error | warning | info | debug
    val logHours: Int = 1,                       // 1 | 6 | 24 | 168 | 0 (keep all)
    // v1.4.0
    val appIcon: String = "corgi",               // corgi | night | mint
    val routingProfiles: List<RoutingProfile> = emptyList(),
    // Apps through the VPN
    val appsMode: String = "all",                // all | only | except
    val apps: Set<String> = emptySet(),
    // Appearance
    val theme: String = "corgi",                 // system | corgi | light | dark
    val materialYou: Boolean = false,
    val amoled: Boolean = false,
    val textScale: Float = 1.0f,
    val lang: String = "system",                 // system | ru | en | uk
    val connectStyle: String = "classic",        // classic | compact
    val vibration: Boolean = true,
    // Providers (subscriptions)
    val autoUpdate: Boolean = true,
    val updateMinutes: Int = 360,
    val notifyUpdates: Boolean = false,
    val updateOnLaunch: Boolean = true,
    val pingOnLaunch: Boolean = false,
    val pingAfterUpdate: Boolean = false,
    val sendHwid: Boolean = true,
    val userAgent: String = DEFAULT_AGENT,
    val sort: String = "default",                // default | ping | name
    // Ping
    val pingMethod: String = "core",             // core | tcp | icmp
    val pingDisplay: String = "digits",          // digits | bar | both | dots
    val pingUrl: String = DEFAULT_PING_URL,
    val pingTimeout: Int = 3,
) {
    init {
        require(routing in ROUTING) { "routing" }
        require(appsMode in listOf("all", "only", "except")) { "apps" }
        require(mtu in 1280..9000) { "mtu" }
        require(RANGE.matches(fragmentLength) && RANGE.matches(fragmentInterval)) { "fragment" }
        require(fragmentPackets in FRAGMENT_PACKETS) { "packets" }
        require(theme in THEMES && lang in LANGS && connectStyle in listOf("classic", "compact")) { "appearance" }
        require(textScale in 0.8f..1.4f) { "text" }
        require(updateMinutes in UPDATE_MINUTES) { "interval" }
        require(sort in SORTS && pingMethod in PING_METHODS && pingDisplay in PING_DISPLAYS) { "list" }
        require(pingTimeout in 1..10 && idleTimeout in 30..3600) { "timeout" }
        require(pingUrl.startsWith("https://") || pingUrl.startsWith("http://")) { "url" }
        require(userAgent.isNotBlank() && userAgent.length <= 200 && userAgent.none { it == '\n' || it == '\r' }) { "agent" }
        require(excludedRoutes.all { CIDR.matches(it) }) { "routes" }
        require(tunnelMode in listOf("tun", "proxy") && logLevel in LOG_LEVELS && logHours in LOG_HOURS) { "mode" }
        require(socksPort in 1024..65535 && httpPort in 1024..65535 && socksPort != httpPort) { "ports" }
        require(muxConcurrency in 1..128) { "mux" }
        require(appIcon in APP_ICONS && routingProfiles.size <= 20 && routingProfiles.map { it.name }.toSet().size == routingProfiles.size) { "icon" }
        require(CREDENTIAL.matches(proxyUser) && CREDENTIAL.matches(proxyPass)) { "credentials" }
        // Sharing the proxy with other devices without a password would open it to the whole network.
        require(!shareLan || proxyAuth) { "auth" }
    }

    fun toJson(): JSONObject = JSONObject().put("routing", routing).put("rules", JSONArray(rules.map { it.toJson() }))
        .put("geoipUrl", geoipUrl).put("geositeUrl", geositeUrl)
        .put("dns", JSONArray(dns)).put("fragment", fragment).put("fragmentPackets", fragmentPackets).put("fragmentLength", fragmentLength)
        .put("fragmentInterval", fragmentInterval).put("mtu", mtu).put("ipv6", ipv6).put("sniffing", sniffing).put("routeOnly", routeOnly)
        .put("blockUdp", blockUdp).put("idleTimeout", idleTimeout).put("excludedRoutes", JSONArray(excludedRoutes))
        .put("appsMode", appsMode).put("apps", JSONArray(apps.sorted()))
        .put("theme", theme).put("materialYou", materialYou).put("amoled", amoled).put("textScale", textScale.toDouble()).put("lang", lang)
        .put("connectStyle", connectStyle).put("vibration", vibration)
        .put("autoUpdate", autoUpdate).put("updateMinutes", updateMinutes).put("notifyUpdates", notifyUpdates).put("updateOnLaunch", updateOnLaunch)
        .put("pingOnLaunch", pingOnLaunch).put("pingAfterUpdate", pingAfterUpdate).put("sendHwid", sendHwid).put("userAgent", userAgent).put("sort", sort)
        .put("tunnelMode", tunnelMode).put("localProxy", localProxy).put("shareLan", shareLan).put("socksPort", socksPort).put("httpPort", httpPort)
        .put("proxyAuth", proxyAuth).put("httpAuth", httpAuth).put("proxyUser", proxyUser).put("proxyPass", proxyPass).put("mux", mux)
        .put("muxConcurrency", muxConcurrency).put("noises", noises).put("speedNotification", speedNotification).put("wakelock", wakelock)
        .put("autoConnectLaunch", autoConnectLaunch).put("autoConnectBoot", autoConnectBoot).put("tileDetails", tileDetails)
        .put("logLevel", logLevel).put("logHours", logHours)
        .put("appIcon", appIcon).put("routingProfiles", JSONArray(routingProfiles.map { it.toJson() }))
        .put("pingMethod", pingMethod).put("pingDisplay", pingDisplay).put("pingUrl", pingUrl).put("pingTimeout", pingTimeout)

    companion object {
        val ROUTING = listOf("global", "bypass_lan", "bypass_ru", "custom")
        val THEMES = listOf("system", "corgi", "light", "dark")
        val LANGS = listOf("system", "ru", "en", "uk")
        val FRAGMENT_PACKETS = listOf("tlshello", "1-3", "1-5")
        val UPDATE_MINUTES = listOf(30, 60, 180, 360, 720, 1440)
        val SORTS = listOf("default", "ping", "name")
        val PING_METHODS = listOf("core", "tcp", "icmp")
        val PING_DISPLAYS = listOf("digits", "bar", "both", "dots")
        val PING_URLS = listOf("https://www.gstatic.com/generate_204", "https://cp.cloudflare.com/generate_204", "https://captive.apple.com/hotspot-detect.html")
        val LOG_LEVELS = listOf("none", "error", "warning", "info", "debug")
        val APP_ICONS = listOf("corgi", "night", "mint")
        val LOG_HOURS = listOf(1, 6, 24, 168, 0)
        private val CREDENTIAL = Regex("^[A-Za-z0-9_.-]{0,64}$")
        const val DEFAULT_PING_URL = "https://www.gstatic.com/generate_204"
        // Remnawave and most panels answer v2ray-style clients with share links or Xray JSON; both are understood.
        const val DEFAULT_AGENT = "v2rayNG/1.10.0 CorgiClient"
        private val RANGE = Regex("^\\d{1,4}(-\\d{1,4})?$")
        val CIDR = Regex("^([0-9]{1,3}(\\.[0-9]{1,3}){3}/\\d{1,2}|[0-9a-fA-F:]+/\\d{1,3})$")
        // runetfreedom/russia-v2ray-rules-dat (GPL-3.0 data files, downloaded by the user's choice, not bundled).
        const val DEFAULT_GEOIP = "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geoip.dat"
        const val DEFAULT_GEOSITE = "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geosite.dat"

        fun of(json: JSONObject?): Settings {
            if (json == null) return Settings()
            val d = Settings()
            fun strings(key: String, fallback: List<String>) = json.optJSONArray(key)?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: fallback
            fun s(key: String, v: String) = json.optString(key, v)
            fun b(key: String, v: Boolean) = json.optBoolean(key, v)
            fun i(key: String, v: Int) = json.optInt(key, v)
            // Field by field: one value out of range falls back to its default, not the whole settings.
            var out = d
            fun tryField(apply: (Settings) -> Settings) { out = runCatching { apply(out) }.getOrDefault(out) }
            tryField { it.copy(routing = s("routing", d.routing)) }
            tryField { it.copy(rules = json.optJSONArray("rules")?.let { a -> (0 until a.length()).map { Rule.of(a.getJSONObject(it)) } } ?: d.rules) }
            tryField { it.copy(geoipUrl = s("geoipUrl", d.geoipUrl), geositeUrl = s("geositeUrl", d.geositeUrl)) }
            tryField { it.copy(dns = strings("dns", d.dns).ifEmpty { d.dns }) }
            tryField { it.copy(fragment = b("fragment", d.fragment), fragmentPackets = s("fragmentPackets", d.fragmentPackets)) }
            tryField { it.copy(fragmentLength = s("fragmentLength", d.fragmentLength), fragmentInterval = s("fragmentInterval", d.fragmentInterval)) }
            tryField { it.copy(mtu = i("mtu", d.mtu)) }
            tryField { it.copy(ipv6 = b("ipv6", d.ipv6), sniffing = b("sniffing", d.sniffing), routeOnly = b("routeOnly", d.routeOnly), blockUdp = b("blockUdp", d.blockUdp)) }
            tryField { it.copy(idleTimeout = i("idleTimeout", d.idleTimeout)) }
            tryField { it.copy(excludedRoutes = strings("excludedRoutes", emptyList())) }
            tryField { it.copy(appsMode = s("appsMode", d.appsMode), apps = strings("apps", emptyList()).toSet()) }
            // Before v1.3.0 «system» was the default theme: it keeps working, new installs get the brand theme.
            tryField { it.copy(theme = s("theme", d.theme)) }
            tryField { it.copy(materialYou = b("materialYou", d.materialYou), amoled = b("amoled", d.amoled), vibration = b("vibration", d.vibration)) }
            tryField { it.copy(textScale = json.optDouble("textScale", 1.0).toFloat()) }
            tryField { it.copy(lang = s("lang", d.lang)) }
            tryField { it.copy(connectStyle = s("connectStyle", d.connectStyle)) }
            tryField { it.copy(autoUpdate = b("autoUpdate", d.autoUpdate), notifyUpdates = b("notifyUpdates", d.notifyUpdates), updateOnLaunch = b("updateOnLaunch", d.updateOnLaunch)) }
            tryField { it.copy(updateMinutes = i("updateMinutes", d.updateMinutes)) }
            tryField { it.copy(pingOnLaunch = b("pingOnLaunch", d.pingOnLaunch), pingAfterUpdate = b("pingAfterUpdate", d.pingAfterUpdate), sendHwid = b("sendHwid", d.sendHwid)) }
            tryField { it.copy(userAgent = s("userAgent", d.userAgent)) }
            tryField { it.copy(sort = s("sort", d.sort)) }
            tryField { it.copy(pingMethod = s("pingMethod", d.pingMethod), pingDisplay = s("pingDisplay", d.pingDisplay)) }
            tryField { it.copy(pingUrl = s("pingUrl", d.pingUrl)) }
            tryField { it.copy(pingTimeout = i("pingTimeout", d.pingTimeout)) }
            tryField { it.copy(tunnelMode = s("tunnelMode", d.tunnelMode), localProxy = b("localProxy", d.localProxy)) }
            tryField { it.copy(socksPort = i("socksPort", d.socksPort), httpPort = i("httpPort", d.httpPort)) }
            tryField { it.copy(proxyUser = s("proxyUser", ""), proxyPass = s("proxyPass", "")) }
            tryField { it.copy(proxyAuth = b("proxyAuth", d.proxyAuth), httpAuth = b("httpAuth", d.httpAuth)) }
            tryField { it.copy(shareLan = b("shareLan", d.shareLan)) }
            tryField { it.copy(mux = b("mux", d.mux), muxConcurrency = i("muxConcurrency", d.muxConcurrency), noises = b("noises", d.noises)) }
            tryField { it.copy(speedNotification = b("speedNotification", d.speedNotification), wakelock = b("wakelock", d.wakelock), tileDetails = b("tileDetails", d.tileDetails)) }
            tryField { it.copy(autoConnectLaunch = b("autoConnectLaunch", d.autoConnectLaunch), autoConnectBoot = b("autoConnectBoot", d.autoConnectBoot)) }
            tryField { it.copy(logLevel = s("logLevel", d.logLevel), logHours = i("logHours", d.logHours)) }
            tryField { it.copy(appIcon = s("appIcon", d.appIcon)) }
            tryField { it.copy(routingProfiles = json.optJSONArray("routingProfiles")?.let { a -> (0 until a.length()).mapNotNull { runCatching { RoutingProfile.of(a.getJSONObject(it)) }.getOrNull() } } ?: emptyList()) }
            return out
        }
    }
}
