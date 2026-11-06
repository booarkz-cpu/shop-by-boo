package shop.remnawave.user.vpn

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.lang.reflect.Proxy

/**
 * The embedded VPN engine: Xray-core through libv2ray.aar (scripts/mobile/build-xray-aar.sh).
 *
 * The library is optional: builds without app/libs/libv2ray.aar keep handing the subscription to
 * an installed client. It is reached by reflection so the app compiles either way.
 */
object XrayEngine {
    private var controller: Any? = null

    fun available(): Boolean = try { Class.forName("libv2ray.Libv2ray"); true } catch (_: Throwable) { false }

    fun version(): String = try {
        Class.forName("libv2ray.Libv2ray").getMethod("checkVersionX").invoke(null) as String
    } catch (_: Throwable) { "" }

    /** Xray config: TUN inbound, the servers, automatic choice of the fastest, and what goes around the VPN. */
    fun config(servers: List<VpnServer>, selected: String, bypassRussian: Boolean, extraDirect: List<String> = emptyList(), tuning: Tuning = Tuning()): String {
        val outbounds = JSONArray()
        servers.forEach { outbounds.put(it.outbound) }
        outbounds.put(JSONObject().put("tag", "direct").put("protocol", "freedom"))
        outbounds.put(JSONObject().put("tag", "block").put("protocol", "blackhole"))
        val rules = JSONArray()
        rules.put(JSONObject().put("type", "field").put("ip", JSONArray(listOf("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
            "169.254.0.0/16", "100.64.0.0/10", "fc00::/7", "fe80::/10"))).put("outboundTag", "direct"))
        if (bypassRussian) rules.put(JSONObject().put("type", "field")
            .put("domain", JSONArray(listOf("regexp:\\.ru$", "regexp:\\.su$", "regexp:\\.xn--p1ai$", "domain:gosuslugi.ru", "domain:nalog.gov.ru",
                "domain:sberbank.com", "domain:vk.com", "domain:vk.me", "domain:userapi.com", "domain:yandex.net", "domain:yandex.com", "domain:yastatic.net") + extraDirect.map { "domain:$it" }))
            .put("outboundTag", "direct"))
        val chosen = servers.firstOrNull { it.name == selected }
        val routing = JSONObject().put("domainStrategy", "AsIs")
        val config = JSONObject()
            .put("log", JSONObject().put("loglevel", "warning"))
            .put("dns", JSONObject().put("servers", JSONArray(listOf("1.1.1.1", "8.8.8.8"))))
            .put("inbounds", JSONArray().put(JSONObject().put("tag", "tun-in").put("protocol", "tun")
                .put("settings", JSONObject().put("name", "xray0").put("mtu", CorgiVpnService.MTU))
                .put("sniffing", JSONObject().put("enabled", true).put("destOverride", JSONArray(listOf("http", "tls", "quic"))))))
            .put("outbounds", outbounds)
        if (chosen != null || servers.size == 1) {
            rules.put(JSONObject().put("type", "field").put("network", "tcp,udp").put("outboundTag", (chosen ?: servers.first()).outbound.getString("tag")))
        } else {
            // Automatic: the server that answers fastest now; a failed one drops out until it answers again.
            config.put("observatory", JSONObject().put("subjectSelector", JSONArray().put("proxy-"))
                .put("probeURL", "https://www.gstatic.com/generate_204").put("probeInterval", "1m").put("enableConcurrency", true))
            routing.put("balancers", JSONArray().put(JSONObject().put("tag", "auto").put("selector", JSONArray().put("proxy-"))
                .put("strategy", JSONObject().put("type", "leastPing")).put("fallbackTag", servers.first().outbound.getString("tag"))))
            rules.put(JSONObject().put("type", "field").put("network", "tcp,udp").put("balancerTag", "auto"))
        }
        config.put("routing", routing.put("rules", rules))
        return tuning.apply(config, if (bypassRussian) 2 else 1).toString()
    }

    /**
     * v28.81.0: a full Xray config from a JSON subscription (Remnawave): its inbounds become the tunnel; what goes
     * around the VPN is put first; geo lists are replaced (geoip:private → the private ranges) or left out, because the
     * app carries no geoip.dat / geosite.dat and Xray would refuse the whole config.
     */
    fun fromJson(raw: String, bypassRussian: Boolean, extraDirect: List<String> = emptyList(), tuning: Tuning = Tuning()): String {
        val config = JSONObject(raw)
        config.put("inbounds", JSONArray().put(JSONObject().put("tag", "tun-in").put("protocol", "tun")
            .put("settings", JSONObject().put("name", "xray0").put("mtu", CorgiVpnService.MTU))
            .put("sniffing", JSONObject().put("enabled", true).put("destOverride", JSONArray(listOf("http", "tls", "quic"))))))
        config.remove("api"); config.remove("stats"); config.remove("metrics")
        val routing = config.optJSONObject("routing") ?: JSONObject().also { config.put("routing", it) }
        val old = routing.optJSONArray("rules") ?: JSONArray()
        val rules = JSONArray()
        rules.put(JSONObject().put("type", "field").put("ip", JSONArray(PRIVATE)).put("outboundTag", DIRECT))
        if (bypassRussian) rules.put(JSONObject().put("type", "field").put("domain", JSONArray(RUSSIAN + extraDirect.map { "domain:$it" })).put("outboundTag", DIRECT))
        for (i in 0 until old.length()) {
            val rule = old.optJSONObject(i) ?: continue
            var emptied = false
            for ((key, ip) in listOf("domain" to false, "ip" to true, "source" to true)) {
                if (!rule.has(key)) continue
                val list = rule.optJSONArray(key) ?: continue
                val out = JSONArray()
                for (j in 0 until list.length()) {
                    val v = list.optString(j)
                    if (ip && v == "geoip:private") PRIVATE.forEach { out.put(it) }
                    else if (!(v.startsWith("geoip:") || v.startsWith("geosite:") || v.startsWith("ext:"))) out.put(list.get(j))
                }
                if (out.length() == 0) { rule.remove(key); emptied = true } else rule.put(key, out)
            }
            if (emptied && listOf("domain", "ip", "source", "port", "network", "protocol", "inboundTag", "user", "attrs").none { rule.has(it) }) continue
            rules.put(rule)
        }
        routing.put("rules", rules)
        config.optJSONObject("dns")?.optJSONArray("servers")?.let { servers ->
            for (i in 0 until servers.length()) servers.optJSONObject(i)?.let { it.remove("domains"); it.remove("expectIPs"); it.remove("expectedIPs") }
        }
        // The «direct» rules need an outbound of that tag.
        val outbounds = config.getJSONArray("outbounds")
        if ((0 until outbounds.length()).none { outbounds.optJSONObject(it)?.optString("tag") == DIRECT })
            outbounds.put(JSONObject().put("tag", DIRECT).put("protocol", "freedom"))
        return tuning.apply(config, if (bypassRussian) 2 else 1).toString()
    }

    private const val DIRECT = "corgi-direct"
    private val PRIVATE = listOf("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10", "fc00::/7", "fe80::/10")
    private val RUSSIAN = listOf("regexp:\\.ru$", "regexp:\\.su$", "regexp:\\.xn--p1ai$", "domain:gosuslugi.ru", "domain:nalog.gov.ru",
        "domain:sberbank.com", "domain:vk.com", "domain:vk.me", "domain:userapi.com", "domain:yandex.net", "domain:yandex.com", "domain:yastatic.net")

    fun start(context: Context, config: String, tunFd: Int, onStop: () -> Unit) {
        val lib = Class.forName("libv2ray.Libv2ray")
        lib.getMethod("initCoreEnv", String::class.java, String::class.java).invoke(null, context.filesDir.absolutePath, "")
        val handlerType = Class.forName("libv2ray.CoreCallbackHandler")
        // gomobile maps Go int to Java long: every callback returns a long.
        val handler = Proxy.newProxyInstance(handlerType.classLoader, arrayOf(handlerType)) { _, method, _ ->
            if (method.name == "shutdown") onStop()
            when (method.returnType) { java.lang.Long.TYPE -> 0L; Integer.TYPE -> 0; else -> null }
        }
        val core = lib.getMethod("newCoreController", handlerType).invoke(null, handler)!!
        core.javaClass.getMethod("startLoop", String::class.java, Integer.TYPE).invoke(core, config, tunFd)
        controller = core
    }

    fun stop() {
        val core = controller ?: return
        controller = null
        try { core.javaClass.getMethod("stopLoop").invoke(core) } catch (_: Throwable) { }
    }

    val running: Boolean get() = controller != null
}
