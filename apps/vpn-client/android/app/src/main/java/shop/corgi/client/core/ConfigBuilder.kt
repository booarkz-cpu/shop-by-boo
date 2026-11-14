package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject

/** Xray configs for the tunnel: from servers (with routing, DNS and TLS fragmentation), or from the user's full JSON. */
object ConfigBuilder {
    const val AUTO = "auto"
    val PRIVATE = listOf("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10", "fc00::/7", "fe80::/10")
    val RUSSIAN_DOMAINS = listOf("regexp:\\.ru$", "regexp:\\.su$", "regexp:\\.xn--p1ai$", "domain:gosuslugi.ru", "domain:nalog.gov.ru",
        "domain:vk.com", "domain:vk.me", "domain:userapi.com", "domain:yandex.net", "domain:yandex.com", "domain:yastatic.net")

    /** v1.7.0: FakeDNS answers 198.18.0.0/15; sniffing then maps those addresses back to the domains. */
    const val FAKE_POOL = "198.18.0.0/15"

    private fun destOverride(fakeDns: Boolean) = JSONArray(listOf("http", "tls", "quic") + if (fakeDns) listOf("fakedns") else emptyList())

    fun tunInbound(mtu: Int, sniffing: Boolean = true, routeOnly: Boolean = true, fakeDns: Boolean = false): JSONObject = JSONObject().put("tag", "tun-in").put("protocol", "tun")
        .put("settings", JSONObject().put("name", "xray0").put("mtu", mtu))
        .put("sniffing", JSONObject().put("enabled", sniffing || fakeDns).put("destOverride", destOverride(fakeDns)).put("routeOnly", routeOnly))

    fun tunInbound(s: Settings): JSONObject = tunInbound(s.mtu, s.sniffing, s.routeOnly, s.fakeDns)

    /** v1.7.0 (N12): own rules as written, or block → proxy → direct. */
    fun ordered(rules: List<Rule>, order: String): List<Rule> =
        if (order == "block_proxy_direct") rules.sortedBy { listOf("block", "proxy", "direct").indexOf(it.action).let { i -> if (i < 0) 3 else i } } else rules

    /**
     * v1.7.0 (N12): the DNS block — FakeDNS first when on, then the remote servers; the direct domains (Russian sites in
     * «РФ напрямую», own «direct» domain rules) are asked from [Settings.localDns] when it is set.
     */
    fun dns(s: Settings, geo: Boolean): JSONObject {
        val servers = JSONArray()
        if (s.fakeDns) servers.put("fakedns")
        s.dns.forEach { servers.put(it) }
        val direct = mutableListOf<String>()
        if (s.routing == "bypass_ru") direct += RUSSIAN_DOMAINS + if (geo) listOf("geosite:ru") else emptyList()
        if (s.routing == "custom" || s.routing == "bypass_ru") direct += s.rules.filter { it.action == "direct" && !it.isIp }
            .filter { geo || !it.match.startsWith("geosite:") }.map { it.match }
        if (s.localDns.isNotBlank() && direct.isNotEmpty()) {
            servers.put(JSONObject().put("address", s.localDns).put("domains", JSONArray(direct.distinct())).put("skipFallback", true))
        }
        return JSONObject().put("servers", servers).put("queryStrategy", if (s.ipv6) "UseIP" else "UseIPv4")
    }

    /**
     * What listens on the device: the tunnel (TUN mode), and the SOCKS5 / HTTP proxy when «только прокси» or
     * «локальный прокси» is on — on 127.0.0.1, or on all interfaces for «доступ через хотспот» (never without a password).
     */
    fun inbounds(s: Settings): JSONArray {
        val list = JSONArray()
        if (s.tunnelMode == "tun") list.put(tunInbound(s))
        if (s.tunnelMode == "proxy" || s.localProxy) {
            val listen = if (s.shareLan) "0.0.0.0" else "127.0.0.1"
            val sniff = JSONObject().put("enabled", s.sniffing || s.fakeDns).put("destOverride", destOverride(s.fakeDns)).put("routeOnly", s.routeOnly)
            val account = JSONArray().put(JSONObject().put("user", s.proxyUser).put("pass", s.proxyPass))
            val socks = JSONObject().put("udp", true).put("ip", if (s.shareLan) "0.0.0.0" else "127.0.0.1")
            if (s.proxyAuth) socks.put("auth", "password").put("accounts", account) else socks.put("auth", "noauth")
            list.put(JSONObject().put("tag", "socks-in").put("protocol", "socks").put("listen", listen).put("port", s.socksPort).put("settings", socks).put("sniffing", sniff))
            val http = JSONObject()
            if (s.proxyAuth && s.httpAuth) http.put("accounts", account)
            list.put(JSONObject().put("tag", "http-in").put("protocol", "http").put("listen", listen).put("port", s.httpPort).put("settings", http).put("sniffing", sniff))
        }
        return list
    }

    /** Mux for the outbound when on — not for XTLS Vision («flow»), Hysteria2, WireGuard or SOCKS, which do not take it. */
    fun mux(outbound: JSONObject, s: Settings) {
        if (!s.mux || outbound.optString("protocol") !in listOf("vless", "vmess", "trojan", "shadowsocks")) return
        val flow = outbound.optJSONObject("settings")?.optJSONArray("vnext")?.optJSONObject(0)?.optJSONArray("users")?.optJSONObject(0)?.optString("flow").orEmpty()
        if (flow.isNotBlank()) return
        outbound.put("mux", JSONObject().put("enabled", true).put("concurrency", s.muxConcurrency).put("xudpConcurrency", s.muxConcurrency).put("xudpProxyUDP443", "reject"))
    }

    /** Logs to files of «Журналы туннеля», counters for the speed in the notification. */
    fun extras(config: JSONObject, s: Settings, logFile: String?, accessFile: String? = null) {
        val log = if (s.logLevel == "none" || logFile == null) JSONObject().put("loglevel", "none")
            else JSONObject().put("loglevel", s.logLevel).put("error", logFile).put("dnsLog", s.logLevel == "debug")
        // v1.7.4 (N12): «Журнал сети» — a line per connection with its route, only while the switch is on.
        if (s.networkLog && accessFile != null) log.put("access", accessFile).put("dnsLog", true)
        config.put("log", log)
        // Counters for the speed on the main screen and in the notification, and (v1.7.3) the traffic by day.
        run {
            config.put("stats", JSONObject())
            val policy = config.optJSONObject("policy") ?: JSONObject().also { config.put("policy", it) }
            policy.put("system", (policy.optJSONObject("system") ?: JSONObject()).put("statsOutboundUplink", true).put("statsOutboundDownlink", true))
        }
    }

    /**
     * ``selected`` — a server's index, or [AUTO]: the fastest of all (observatory + leastPing balancer).
     * ``geo`` — geoip.dat and geosite.dat are present (rules with geoip:/geosite: need them).
     */
    fun build(servers: List<Server>, selected: String, s: Settings, geo: Boolean): String {
        require(servers.isNotEmpty()) { "no servers" }
        val outbounds = JSONArray()
        servers.forEachIndexed { i, server ->
            val row = JSONObject(server.outbound.toString()).put("tag", "proxy-$i")
            mux(row, s)
            if (s.fragment && row.has("streamSettings") && row.getJSONObject("streamSettings").optString("security") == "tls") {
                row.getJSONObject("streamSettings").put("sockopt", JSONObject().put("dialerProxy", "fragment"))
            }
            outbounds.put(row)
        }
        outbounds.put(JSONObject().put("tag", "direct").put("protocol", "freedom")
            .put("settings", JSONObject().put("domainStrategy", if (s.ipv6) "UseIP" else "UseIPv4")))
        outbounds.put(JSONObject().put("tag", "block").put("protocol", "blackhole"))
        // v1.7.0 (N12): with FakeDNS or a local DNS the apps' own lookups (port 53 from the device) are answered by Xray's DNS.
        val hijackDns = s.fakeDns || s.localDns.isNotBlank()
        if (hijackDns) outbounds.put(JSONObject().put("tag", "dns-out").put("protocol", "dns"))
        if (s.fragment) outbounds.put(JSONObject().put("tag", "fragment").put("protocol", "freedom").put("settings", JSONObject()
            .put("fragment", JSONObject().put("packets", s.fragmentPackets).put("length", s.fragmentLength).put("interval", s.fragmentInterval))
            .apply { if (s.noises) put("noises", JSONArray().put(JSONObject().put("type", "rand").put("packet", "10-20").put("delay", "10-16"))) }))

        val rules = JSONArray()
        // Only lookups that came in from the device (not Xray's own queries to the DNS servers — that would loop).
        if (hijackDns) rules.put(JSONObject().put("type", "field").put("inboundTag", JSONArray(listOf("tun-in", "socks-in", "http-in")))
            .put("port", "53").put("outboundTag", "dns-out"))
        // «Исключённые маршруты»: these addresses never go through the server.
        if (s.excludedRoutes.isNotEmpty()) rules.put(JSONObject().put("type", "field").put("ip", JSONArray(s.excludedRoutes)).put("outboundTag", "direct"))
        // v1.5.0: ads are blocked before any other rule, in every routing mode (the list is in geosite.dat).
        if (s.adBlock && geo) rules.put(JSONObject().put("type", "field").put("domain", JSONArray().put(AD_LIST)).put("outboundTag", "block"))
        if (s.blockUdp) rules.put(JSONObject().put("type", "field").put("network", "udp").put("port", "1-52,54-65535").put("outboundTag", "block"))
        if (s.routing != "global") rules.put(JSONObject().put("type", "field").put("ip", JSONArray(PRIVATE)).put("outboundTag", "direct"))
        if (s.routing == "bypass_ru") {
            rules.put(JSONObject().put("type", "field").put("domain", JSONArray(RUSSIAN_DOMAINS + if (geo) listOf("geosite:ru") else emptyList()))
                .put("outboundTag", "direct"))
            if (geo) rules.put(JSONObject().put("type", "field").put("ip", JSONArray().put("geoip:ru")).put("outboundTag", "direct"))
        }
        if (s.routing == "custom" || s.routing == "bypass_ru") {
            for (rule in ordered(s.rules, s.ruleOrder)) {
                val geoRule = rule.match.startsWith("geoip:") || rule.match.startsWith("geosite:")
                if (geoRule && !geo) continue  // without the files Xray would refuse the whole config
                val target = if (rule.action == "proxy") null else rule.action
                val row = JSONObject().put("type", "field").put(if (rule.isIp) "ip" else "domain", JSONArray().put(rule.match))
                if (target != null) row.put("outboundTag", target) else if (selected == AUTO && servers.size > 1) row.put("balancerTag", "auto")
                else row.put("outboundTag", "proxy-${index(selected, servers)}")
                rules.put(row)
            }
        }
        val routing = JSONObject().put("domainStrategy", if (s.domainStrategy != "auto") s.domainStrategy else if (geo) "IPIfNonMatch" else "AsIs")
        val config = JSONObject()
            .put("log", JSONObject().put("loglevel", "warning"))
            .put("dns", dns(s, geo))
            .put("inbounds", inbounds(s))
            .put("outbounds", outbounds)
            .put("policy", JSONObject().put("levels", JSONObject().put("0", JSONObject().put("connIdle", s.idleTimeout))))
        if (s.fakeDns) config.put("fakedns", JSONArray().put(JSONObject().put("ipPool", FAKE_POOL).put("poolSize", 65535)))
        if (selected == AUTO && servers.size > 1) {
            config.put("observatory", JSONObject().put("subjectSelector", JSONArray().put("proxy-"))
                .put("probeURL", "https://www.gstatic.com/generate_204").put("probeInterval", "1m").put("enableConcurrency", true))
            routing.put("balancers", JSONArray().put(JSONObject().put("tag", "auto").put("selector", JSONArray().put("proxy-"))
                .put("strategy", JSONObject().put("type", "leastPing")).put("fallbackTag", "proxy-0")))
            rules.put(JSONObject().put("type", "field").put("network", "tcp,udp").put("balancerTag", "auto"))
        } else {
            rules.put(JSONObject().put("type", "field").put("network", "tcp,udp").put("outboundTag", "proxy-${index(selected, servers)}"))
        }
        return config.put("routing", routing.put("rules", rules)).toString()
    }

    private fun index(selected: String, servers: List<Server>): Int = selected.toIntOrNull()?.takeIf { it in servers.indices } ?: 0

    /**
     * A full Xray config the user imported (observatory, balancers, routing, own outbounds stay as written). Its inbounds
     * are replaced with the tunnel; anything that would listen on the device (socks, http, dokodemo) is not kept.
     */
    fun fromJson(raw: String, s: Settings, geo: Boolean = true): String {
        val config = JSONObject(raw)
        val outbounds = config.optJSONArray("outbounds")
        require(outbounds != null && outbounds.length() > 0) { "no outbounds" }
        config.put("inbounds", inbounds(s))
        config.remove("api"); config.remove("stats"); config.remove("metrics")
        if (!geo) stripGeo(config)
        return config.toString()
    }

    /**
     * Without geoip.dat / geosite.dat Xray refuses a config that names them (panels put «geoip:private», «geosite:…» into
     * their JSON). Then «geoip:private» becomes the private ranges themselves and other geo entries are left out —
     * the rule keeps what it can, a rule left empty is dropped; DNS servers lose their geo domain lists the same way.
     */
    fun stripGeo(config: JSONObject) {
        fun clean(list: JSONArray?, ip: Boolean): JSONArray? {
            if (list == null) return null
            val out = JSONArray()
            for (i in 0 until list.length()) {
                val v = list.optString(i)
                when {
                    ip && v == "geoip:private" -> PRIVATE.forEach { out.put(it) }
                    v.startsWith("geoip:") || v.startsWith("geosite:") || v.startsWith("ext:") -> Unit
                    else -> out.put(list.get(i))
                }
            }
            return out
        }
        config.optJSONObject("routing")?.optJSONArray("rules")?.let { rules ->
            val kept = JSONArray()
            for (i in 0 until rules.length()) {
                val rule = rules.optJSONObject(i) ?: continue
                var emptied = false
                for ((key, ip) in listOf("domain" to false, "ip" to true, "source" to true)) {
                    if (!rule.has(key)) continue
                    val list = clean(rule.optJSONArray(key), ip)
                    if (list == null || list.length() == 0) { rule.remove(key); emptied = true } else rule.put(key, list)
                }
                // A rule that only matched geo lists would now match everything: it goes.
                val matchers = listOf("domain", "ip", "source", "port", "network", "protocol", "inboundTag", "user", "attrs", "sourcePort")
                if (emptied && matchers.none { rule.has(it) }) continue
                kept.put(rule)
            }
            config.getJSONObject("routing").put("rules", kept)
        }
        config.optJSONObject("dns")?.optJSONArray("servers")?.let { servers ->
            for (i in 0 until servers.length()) {
                val server = servers.optJSONObject(i) ?: continue
                for ((key, ip) in listOf("domains" to false, "expectIPs" to true, "expectedIPs" to true)) {
                    if (!server.has(key)) continue
                    val list = clean(server.optJSONArray(key), ip)
                    if (list == null || list.length() == 0) server.remove(key) else server.put(key, list)
                }
            }
        }
    }

    /** Geo rules the config uses (to tell the user to download the files first). */
    const val AD_LIST = "geosite:category-ads-all"

    fun needsGeo(raw: String): Boolean = Regex("\"geo(ip|site):").containsMatchIn(raw)
}
