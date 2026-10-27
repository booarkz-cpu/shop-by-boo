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
    fun config(servers: List<VpnServer>, selected: String, bypassRussian: Boolean): String {
        val outbounds = JSONArray()
        servers.forEach { outbounds.put(it.outbound) }
        outbounds.put(JSONObject().put("tag", "direct").put("protocol", "freedom"))
        outbounds.put(JSONObject().put("tag", "block").put("protocol", "blackhole"))
        val rules = JSONArray()
        rules.put(JSONObject().put("type", "field").put("ip", JSONArray(listOf("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
            "169.254.0.0/16", "100.64.0.0/10", "fc00::/7", "fe80::/10"))).put("outboundTag", "direct"))
        if (bypassRussian) rules.put(JSONObject().put("type", "field")
            .put("domain", JSONArray(listOf("regexp:\\.ru$", "regexp:\\.su$", "regexp:\\.xn--p1ai$", "domain:gosuslugi.ru", "domain:nalog.gov.ru")))
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
        return config.toString()
    }

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
