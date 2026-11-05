package shop.remnawave.user.vpn

import android.net.Uri
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject

/** One server of the subscription: its name and the Xray outbound built from its share link. */
data class VpnServer(val name: String, val outbound: JSONObject)

/**
 * Share links of a subscription (vless://, vmess://, trojan://, ss://) → Xray outbounds.
 * Remnawave answers the subscription URL with base64 lines of such links for v2ray clients.
 */
object ShareLinks {
    fun decodeSubscription(body: String): List<String> {
        val text = body.trim()
        val plain = if (text.contains("://")) text else try {
            String(Base64.decode(text.replace("\n", "").replace("\r", ""), Base64.DEFAULT or Base64.NO_WRAP), Charsets.UTF_8)
        } catch (_: IllegalArgumentException) {
            String(Base64.decode(text, Base64.URL_SAFE or Base64.NO_WRAP), Charsets.UTF_8)
        }
        return plain.lines().map { it.trim() }.filter { it.contains("://") && !it.startsWith("http") }
    }

    private val PROXY_PROTOCOLS = setOf("vless", "vmess", "trojan", "shadowsocks", "socks", "wireguard", "hysteria")

    /**
     * v28.81.0: Remnawave answers v2rayNG / Happ with Xray JSON when its response rules say so — an array of full
     * configs with «remarks» (the first is often «fastest» with its own balancer). Returns (name, config) or null when
     * the body is not JSON.
     */
    fun jsonConfigs(body: String): List<Pair<String, String>>? {
        val text = body.trim().removePrefix("\uFEFF")
        if (!(text.startsWith("[") || text.startsWith("{"))) return null
        val items = try { if (text.startsWith("[")) JSONArray(text) else JSONArray().put(JSONObject(text)) } catch (_: Exception) { return null }
        val out = mutableListOf<Pair<String, String>>()
        for (i in 0 until items.length()) {
            val item = items.optJSONObject(i) ?: continue
            val outbounds = item.optJSONArray("outbounds") ?: continue
            if ((0 until outbounds.length()).none { outbounds.optJSONObject(it)?.optString("protocol") in PROXY_PROTOCOLS }) continue
            out += item.optString("remarks").ifBlank { "Server ${i + 1}" }.take(80) to item.toString()
        }
        return out
    }

    /** Servers of either kind of subscription body (for counts and checks): the proxy outbound of each JSON config, or the links. */
    fun servers(body: String): List<VpnServer> = jsonConfigs(body)?.mapNotNull { (name, config) ->
        val outbounds = JSONObject(config).optJSONArray("outbounds") ?: return@mapNotNull null
        (0 until outbounds.length()).mapNotNull { outbounds.optJSONObject(it) }.firstOrNull { it.optString("protocol") in PROXY_PROTOCOLS }
            ?.let { VpnServer(name, it) }
    } ?: parseAll(body)

    fun parseAll(body: String): List<VpnServer> = decodeSubscription(body).mapIndexedNotNull { i, link ->
        try { parse(link, "proxy-$i") } catch (_: Exception) { null }
    }

    fun parse(link: String, tag: String): VpnServer? = when {
        link.startsWith("vless://") -> vless(link, tag)
        link.startsWith("vmess://") -> vmess(link, tag)
        link.startsWith("trojan://") -> trojan(link, tag)
        link.startsWith("ss://") -> shadowsocks(link, tag)
        link.startsWith("hysteria2://") || link.startsWith("hy2://") -> hysteria2(link, tag)
        else -> null
    }

    private fun name(uri: Uri, fallback: String) = Uri.decode(uri.fragment ?: "").ifBlank { fallback }

    private fun q(uri: Uri, key: String) = uri.getQueryParameter(key).orEmpty()

    private fun vless(link: String, tag: String): VpnServer {
        val uri = Uri.parse(link)
        val user = JSONObject().put("id", uri.userInfo.orEmpty()).put("encryption", q(uri, "encryption").ifBlank { "none" })
        if (q(uri, "flow").isNotBlank()) user.put("flow", q(uri, "flow"))
        val settings = JSONObject().put("vnext", JSONArray().put(JSONObject().put("address", uri.host).put("port", uri.port).put("users", JSONArray().put(user))))
        return VpnServer(name(uri, uri.host ?: tag), outbound(tag, "vless", settings, stream(uri, q(uri, "type"), q(uri, "security"))))
    }

    private fun trojan(link: String, tag: String): VpnServer {
        val uri = Uri.parse(link)
        val settings = JSONObject().put("servers", JSONArray().put(JSONObject().put("address", uri.host).put("port", uri.port).put("password", Uri.decode(uri.userInfo.orEmpty()))))
        return VpnServer(name(uri, uri.host ?: tag), outbound(tag, "trojan", settings, stream(uri, q(uri, "type"), q(uri, "security").ifBlank { "tls" })))
    }

    private fun vmess(link: String, tag: String): VpnServer {
        val json = JSONObject(String(Base64.decode(link.removePrefix("vmess://"), Base64.DEFAULT), Charsets.UTF_8))
        val user = JSONObject().put("id", json.optString("id")).put("alterId", json.optInt("aid", 0)).put("security", json.optString("scy").ifBlank { "auto" })
        val settings = JSONObject().put("vnext", JSONArray().put(JSONObject().put("address", json.optString("add")).put("port", json.optInt("port")).put("users", JSONArray().put(user))))
        val params = mapOf("type" to json.optString("net"), "host" to json.optString("host"), "path" to json.optString("path"), "sni" to json.optString("sni"),
            "alpn" to json.optString("alpn"), "fp" to json.optString("fp"), "headerType" to json.optString("type"), "serviceName" to json.optString("path"))
        val stream = streamOf(params, json.optString("net"), if (json.optString("tls") == "tls") "tls" else "none", json.optString("add"))
        return VpnServer(json.optString("ps").ifBlank { json.optString("add") }, outbound(tag, "vmess", settings, stream))
    }

    private fun shadowsocks(link: String, tag: String): VpnServer {
        val uri = Uri.parse(link)
        val method: String
        val password: String
        val host: String
        val port: Int
        if (uri.host != null && uri.port > 0) {
            val info = Uri.decode(uri.userInfo.orEmpty())
            val decoded = if (info.contains(":")) info else String(Base64.decode(info, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING), Charsets.UTF_8)
            method = decoded.substringBefore(":"); password = decoded.substringAfter(":"); host = uri.host!!; port = uri.port
        } else {
            val raw = String(Base64.decode(link.removePrefix("ss://").substringBefore("#"), Base64.DEFAULT), Charsets.UTF_8)
            method = raw.substringBefore(":"); password = raw.substringAfter(":").substringBeforeLast("@")
            host = raw.substringAfterLast("@").substringBeforeLast(":"); port = raw.substringAfterLast(":").toInt()
        }
        val settings = JSONObject().put("servers", JSONArray().put(JSONObject().put("address", host).put("port", port).put("method", method).put("password", password)))
        return VpnServer(name(uri, host), outbound(tag, "shadowsocks", settings, null))
    }

    /** hysteria2://auth@host:port?sni=…&alpn=h3 → Xray «hysteria» version 2; links with obfs are skipped. */
    private fun hysteria2(link: String, tag: String): VpnServer? {
        val uri = Uri.parse(link.replaceFirst("hy2://", "hysteria2://"))
        if (q(uri, "obfs").isNotBlank() || uri.host == null || uri.port <= 0) return null
        val tls = JSONObject().put("serverName", q(uri, "sni").ifBlank { uri.host }).put("alpn", JSONArray(q(uri, "alpn").ifBlank { "h3" }.split(",")))
        if (q(uri, "insecure") == "1") tls.put("allowInsecure", true)
        val stream = JSONObject().put("network", "hysteria").put("security", "tls").put("tlsSettings", tls)
            .put("hysteriaSettings", JSONObject().put("version", 2).put("auth", Uri.decode(uri.userInfo.orEmpty())))
        val settings = JSONObject().put("version", 2).put("address", uri.host).put("port", uri.port)
        return VpnServer(name(uri, uri.host ?: tag), outbound(tag, "hysteria", settings, stream))
    }

    private fun outbound(tag: String, protocol: String, settings: JSONObject, stream: JSONObject?): JSONObject {
        val row = JSONObject().put("tag", tag).put("protocol", protocol).put("settings", settings)
        if (stream != null) row.put("streamSettings", stream)
        return row
    }

    private fun stream(uri: Uri, network: String, security: String): JSONObject {
        val params = uri.queryParameterNames.associateWith { q(uri, it) }
        return streamOf(params, network, security, uri.host.orEmpty())
    }

    /** streamSettings of Xray: transport (tcp, ws, grpc, xhttp, httpupgrade) and security (tls, reality). */
    fun streamOf(p: Map<String, String>, rawNetwork: String, rawSecurity: String, host: String): JSONObject {
        val network = when (rawNetwork.ifBlank { "tcp" }) { "h2", "http" -> "xhttp"; "splithttp" -> "xhttp"; else -> rawNetwork.ifBlank { "tcp" } }
        val stream = JSONObject().put("network", network)
        val path = Uri.decode(p["path"].orEmpty())
        val hostHeader = p["host"].orEmpty()
        when (network) {
            "ws" -> stream.put("wsSettings", JSONObject().put("path", path.ifBlank { "/" }).apply { if (hostHeader.isNotBlank()) put("host", hostHeader) })
            "grpc" -> stream.put("grpcSettings", JSONObject().put("serviceName", p["serviceName"].orEmpty().ifBlank { path }).put("multiMode", p["mode"] == "multi"))
            "xhttp" -> stream.put("xhttpSettings", JSONObject().put("path", path.ifBlank { "/" }).put("mode", p["mode"].orEmpty().ifBlank { "auto" }).apply { if (hostHeader.isNotBlank()) put("host", hostHeader) })
            "httpupgrade" -> stream.put("httpupgradeSettings", JSONObject().put("path", path.ifBlank { "/" }).apply { if (hostHeader.isNotBlank()) put("host", hostHeader) })
            "tcp" -> if (p["headerType"] == "http") stream.put("tcpSettings", JSONObject().put("header", JSONObject().put("type", "http")
                .put("request", JSONObject().put("path", JSONArray().put(path.ifBlank { "/" })).put("headers", JSONObject().put("Host", JSONArray().put(hostHeader.ifBlank { host }))))))
        }
        val sni = p["sni"].orEmpty().ifBlank { p["peer"].orEmpty() }.ifBlank { hostHeader.ifBlank { host } }
        val fingerprint = p["fp"].orEmpty().ifBlank { "chrome" }
        when (rawSecurity) {
            "tls" -> stream.put("security", "tls").put("tlsSettings", JSONObject().put("serverName", sni).put("fingerprint", fingerprint)
                .apply { p["alpn"]?.takeIf { it.isNotBlank() }?.let { put("alpn", JSONArray(Uri.decode(it).split(","))) } })
            "reality" -> stream.put("security", "reality").put("realitySettings", JSONObject().put("serverName", sni).put("fingerprint", fingerprint)
                .put("publicKey", p["pbk"].orEmpty()).put("shortId", p["sid"].orEmpty()).put("spiderX", Uri.decode(p["spx"].orEmpty())))
            else -> stream.put("security", "none")
        }
        return stream
    }
}
