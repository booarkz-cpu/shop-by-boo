package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject

/** Xray configs for the tunnel: from servers (with routing, DNS and TLS fragmentation), or from the user's full JSON. */
object ConfigBuilder {
    const val AUTO = "auto"
    val PRIVATE = listOf("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10", "fc00::/7", "fe80::/10")
    val RUSSIAN_DOMAINS = listOf("regexp:\\.ru$", "regexp:\\.su$", "regexp:\\.xn--p1ai$", "domain:gosuslugi.ru", "domain:nalog.gov.ru",
        "domain:vk.com", "domain:vk.me", "domain:userapi.com", "domain:yandex.net", "domain:yandex.com", "domain:yastatic.net")

    fun tunInbound(mtu: Int): JSONObject = JSONObject().put("tag", "tun-in").put("protocol", "tun")
        .put("settings", JSONObject().put("name", "xray0").put("mtu", mtu))
        .put("sniffing", JSONObject().put("enabled", true).put("destOverride", JSONArray(listOf("http", "tls", "quic"))))

    /**
     * ``selected`` — a server's index, or [AUTO]: the fastest of all (observatory + leastPing balancer).
     * ``geo`` — geoip.dat and geosite.dat are present (rules with geoip:/geosite: need them).
     */
    fun build(servers: List<Server>, selected: String, s: Settings, geo: Boolean): String {
        require(servers.isNotEmpty()) { "no servers" }
        val outbounds = JSONArray()
        servers.forEachIndexed { i, server ->
            val row = JSONObject(server.outbound.toString()).put("tag", "proxy-$i")
            if (s.fragment && row.has("streamSettings") && row.getJSONObject("streamSettings").optString("security") == "tls") {
                row.getJSONObject("streamSettings").put("sockopt", JSONObject().put("dialerProxy", "fragment"))
            }
            outbounds.put(row)
        }
        outbounds.put(JSONObject().put("tag", "direct").put("protocol", "freedom")
            .put("settings", JSONObject().put("domainStrategy", if (s.ipv6) "UseIP" else "UseIPv4")))
        outbounds.put(JSONObject().put("tag", "block").put("protocol", "blackhole"))
        if (s.fragment) outbounds.put(JSONObject().put("tag", "fragment").put("protocol", "freedom").put("settings", JSONObject()
            .put("fragment", JSONObject().put("packets", "tlshello").put("length", s.fragmentLength).put("interval", s.fragmentInterval))))

        val rules = JSONArray()
        if (s.routing != "global") rules.put(JSONObject().put("type", "field").put("ip", JSONArray(PRIVATE)).put("outboundTag", "direct"))
        if (s.routing == "bypass_ru") {
            rules.put(JSONObject().put("type", "field").put("domain", JSONArray(RUSSIAN_DOMAINS + if (geo) listOf("geosite:ru") else emptyList()))
                .put("outboundTag", "direct"))
            if (geo) rules.put(JSONObject().put("type", "field").put("ip", JSONArray().put("geoip:ru")).put("outboundTag", "direct"))
        }
        if (s.routing == "custom" || s.routing == "bypass_ru") {
            for (rule in s.rules) {
                val geoRule = rule.match.startsWith("geoip:") || rule.match.startsWith("geosite:")
                if (geoRule && !geo) continue  // without the files Xray would refuse the whole config
                val target = if (rule.action == "proxy") null else rule.action
                val row = JSONObject().put("type", "field").put(if (rule.isIp) "ip" else "domain", JSONArray().put(rule.match))
                if (target != null) row.put("outboundTag", target) else if (selected == AUTO && servers.size > 1) row.put("balancerTag", "auto")
                else row.put("outboundTag", "proxy-${index(selected, servers)}")
                rules.put(row)
            }
        }
        val routing = JSONObject().put("domainStrategy", if (geo) "IPIfNonMatch" else "AsIs")
        val config = JSONObject()
            .put("log", JSONObject().put("loglevel", "warning"))
            .put("dns", JSONObject().put("servers", JSONArray(s.dns)).put("queryStrategy", if (s.ipv6) "UseIP" else "UseIPv4"))
            .put("inbounds", JSONArray().put(tunInbound(s.mtu)))
            .put("outbounds", outbounds)
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
    fun fromJson(raw: String, s: Settings): String {
        val config = JSONObject(raw)
        val outbounds = config.optJSONArray("outbounds")
        require(outbounds != null && outbounds.length() > 0) { "no outbounds" }
        config.put("inbounds", JSONArray().put(tunInbound(s.mtu)))
        config.remove("api"); config.remove("stats"); config.remove("metrics")
        return config.toString()
    }

    /** Geo rules the config uses (to tell the user to download the files first). */
    fun needsGeo(raw: String): Boolean = Regex("\"geo(ip|site):").containsMatchIn(raw)
}
