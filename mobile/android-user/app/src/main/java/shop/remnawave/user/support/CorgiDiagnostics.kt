package shop.remnawave.user.support

import org.json.JSONArray
import org.json.JSONObject
import shop.remnawave.user.security.CorgiMirrors
import shop.remnawave.user.vpn.ShareLinks
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URL

/**
 * «Не работает VPN»: what the phone can see from its own network, sent to POST /api/me/diagnostics together with
 * the customer's words. The shop adds the subscription, device limit and node state and answers with the likely cause.
 * Runs off the main thread; every check has a short timeout so the whole report takes seconds.
 */
object CorgiDiagnostics {
    private fun check(name: String, target: String, block: () -> String): JSONObject {
        val started = System.nanoTime()
        return try {
            val detail = block()
            JSONObject().put("name", name).put("target", target.take(200)).put("ok", true)
                .put("ms", ((System.nanoTime() - started) / 1_000_000).toInt()).put("detail", detail.take(300))
        } catch (exc: Exception) {
            JSONObject().put("name", name).put("target", target.take(200)).put("ok", false)
                .put("detail", "${exc.javaClass.simpleName}: ${exc.message.orEmpty()}".take(300))
        }
    }

    private fun get(url: String, userAgent: String): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 6000; readTimeout = 8000; instanceFollowRedirects = true
            setRequestProperty("User-Agent", userAgent)
        }
        val code = connection.responseCode
        if (code !in 200..299) throw IllegalStateException("HTTP $code")
        return connection.inputStream.bufferedReader().use { it.readText().take(512 * 1024) }
    }

    /** host:port of every server in the subscription (vless/vmess: vnext, trojan/shadowsocks: servers). */
    private fun endpoints(body: String): List<Pair<String, Int>> = ShareLinks.parseAll(body).mapNotNull { server ->
        val settings = server.outbound.optJSONObject("settings") ?: return@mapNotNull null
        val first = (settings.optJSONArray("vnext") ?: settings.optJSONArray("servers"))?.optJSONObject(0) ?: return@mapNotNull null
        val host = first.optString("address"); val port = first.optInt("port")
        if (host.isBlank() || port !in 1..65535) null else host to port
    }.distinct().take(12)

    /** Connection quality (connection_quality.py): only the server checks, with the carrier and the network type. */
    fun quality(context: android.content.Context, base: String, subscriptionUrl: String): JSONObject {
        val checks = run(base, subscriptionUrl)
        val results = JSONArray()
        for (i in 0 until checks.length()) {
            val c = checks.optJSONObject(i) ?: continue
            if (c.optString("name") == "server") results.put(JSONObject().put("server", c.optString("target")).put("ok", c.optBoolean("ok"))
                .apply { if (c.has("ms")) put("ms", c.optInt("ms")) })
        }
        val telephony = context.getSystemService(android.content.Context.TELEPHONY_SERVICE) as? android.telephony.TelephonyManager
        val connectivity = context.getSystemService(android.content.Context.CONNECTIVITY_SERVICE) as? android.net.ConnectivityManager
        val caps = connectivity?.getNetworkCapabilities(connectivity.activeNetwork)
        val network = when {
            caps == null -> "other"
            caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "other"
        }
        return JSONObject().put("platform", "android").put("carrier", telephony?.networkOperatorName.orEmpty().take(64))
            .put("network", network).put("country", telephony?.networkCountryIso.orEmpty().take(2)).put("results", results)
    }

    fun run(base: String, subscriptionUrl: String): JSONArray {
        val checks = JSONArray()
        val origin = CorgiMirrors.resolve(base)
        val host = try { URL(origin).host } catch (_: Exception) { "" }
        checks.put(check("dns", host) { InetAddress.getAllByName(host).joinToString { it.hostAddress ?: "" } })
        checks.put(check("api", "$origin/health/live") { get("$origin/health/live", "CorgiLusi-Android-User/3.4.0"); "ok" })
        var body = ""
        checks.put(check("subscription", "") {
            body = get(subscriptionUrl, "v2rayNG/1.10.0 CorgiLusi")
            "${ShareLinks.parseAll(body).size} серверов"
        })
        for ((address, port) in if (body.isBlank()) emptyList() else endpoints(body)) {
            checks.put(check("server", "$address:$port") { Socket().use { it.connect(InetSocketAddress(address, port), 5000) }; "tcp" })
        }
        return checks
    }
}
