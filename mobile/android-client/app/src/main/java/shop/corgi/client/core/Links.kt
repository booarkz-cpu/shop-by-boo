package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.net.URLDecoder
import java.util.Base64

/** One server: its name, the protocol and the Xray outbound built from its share link (tag set when the config is built). */
data class Server(val name: String, val protocol: String, val outbound: JSONObject, val link: String) {
    val host: String get() = when (protocol) {
        "vless", "vmess" -> outbound.getJSONObject("settings").let { st -> st.optJSONArray("vnext")?.optJSONObject(0)?.optString("address") ?: st.optString("address") }
        "wireguard" -> outbound.getJSONObject("settings").getJSONArray("peers").getJSONObject(0).optString("endpoint").substringBeforeLast(":")
        "hysteria" -> outbound.getJSONObject("settings").optString("address")
        else -> outbound.getJSONObject("settings").optJSONArray("servers")?.optJSONObject(0)?.optString("address").orEmpty()
    }
    val port: Int get() = when (protocol) {
        "vless", "vmess" -> outbound.getJSONObject("settings").let { st -> st.optJSONArray("vnext")?.optJSONObject(0)?.optInt("port") ?: st.optInt("port") }
        "wireguard" -> outbound.getJSONObject("settings").getJSONArray("peers").getJSONObject(0).optString("endpoint").substringAfterLast(":").toIntOrNull() ?: 0
        "hysteria" -> outbound.getJSONObject("settings").optInt("port")
        else -> outbound.getJSONObject("settings").optJSONArray("servers")?.optJSONObject(0)?.optInt("port") ?: 0
    }
}

/**
 * Share links → Xray outbounds: vless (REALITY, TLS, ws, grpc, xhttp, httpupgrade), vmess, trojan, ss, socks and
 * wireguard. Pure JVM code (java.net.URI, java.util.Base64) so it is unit-tested without a device.
 * Hysteria2 (Xray 26: protocol «hysteria», version 2) is built too; TUIC and Hysteria v1 are recognised and skipped.
 */
object Links {
    val SCHEMES = listOf("vless://", "vmess://", "trojan://", "ss://", "socks://", "socks5://", "wireguard://", "wg://", "hysteria2://", "hy2://")
    val UNSUPPORTED = listOf("hysteria://", "tuic://")
    private val PROXY_PROTOCOLS = setOf("vless", "vmess", "trojan", "shadowsocks", "socks", "wireguard", "hysteria")

    /**
     * A subscription answered with Xray JSON (Remnawave does so for v2rayNG / Happ when its response rules say so):
     * an array of full configs (or one config), each with «remarks». Returns (name, config) per entry, or null when
     * the body is not JSON. Entries without a proxy outbound are skipped.
     */
    fun jsonConfigs(body: String): List<Pair<String, String>>? {
        val text = body.trim().removePrefix("\uFEFF")
        if (!(text.startsWith("[") || text.startsWith("{"))) return null
        val items = runCatching { if (text.startsWith("[")) JSONArray(text) else JSONArray().put(JSONObject(text)) }.getOrNull() ?: return null
        val out = mutableListOf<Pair<String, String>>()
        for (i in 0 until items.length()) {
            val item = items.optJSONObject(i) ?: continue
            val outbounds = item.optJSONArray("outbounds") ?: continue
            if ((0 until outbounds.length()).none { outbounds.optJSONObject(it)?.optString("protocol") in PROXY_PROTOCOLS }) continue
            out += item.optString("remarks").ifBlank { "Server ${i + 1}" }.take(80) to item.toString()
        }
        return out
    }

    /** The first proxy outbound of a JSON config (for its address, protocol and latency check). */
    fun firstProxy(config: String): JSONObject? = runCatching {
        val outbounds = JSONObject(config).getJSONArray("outbounds")
        (0 until outbounds.length()).map { outbounds.getJSONObject(it) }.firstOrNull { it.optString("protocol") in PROXY_PROTOCOLS }
    }.getOrNull()

    /** A subscription body: base64 (standard or URL-safe) or plain lines of links. */
    fun decodeBody(body: String): List<String> {
        val text = body.trim().removePrefix("﻿")
        val plain = if (text.contains("://")) text else b64(text.replace("\n", "").replace("\r", "")) ?: text
        return plain.lines().map { it.trim() }.filter { line -> (SCHEMES + UNSUPPORTED).any { line.startsWith(it, ignoreCase = true) } }
    }

    /** Servers of a body and how many links were skipped (unsupported protocol or broken). */
    fun parseBody(body: String): Pair<List<Server>, Int> {
        val links = decodeBody(body)
        val servers = links.mapNotNull { runCatching { parse(it) }.getOrNull() }
        return servers to (links.size - servers.size)
    }

    fun parse(link: String): Server? {
        val lower = link.lowercase()
        return when {
            lower.startsWith("vless://") -> vless(link)
            lower.startsWith("vmess://") -> vmess(link)
            lower.startsWith("trojan://") -> trojan(link)
            lower.startsWith("ss://") -> shadowsocks(link)
            lower.startsWith("socks://") || lower.startsWith("socks5://") -> socks(link)
            lower.startsWith("wireguard://") || lower.startsWith("wg://") -> wireguard(link)
            lower.startsWith("hysteria2://") || lower.startsWith("hy2://") -> hysteria2(link)
            else -> null
        }
    }

    fun b64(value: String): String? {
        val clean = value.trim().trimEnd('=')
        for (decoder in listOf(Base64.getDecoder(), Base64.getUrlDecoder())) {
            try {
                val padded = clean + "=".repeat((4 - clean.length % 4) % 4)
                return String(decoder.decode(padded), Charsets.UTF_8)
            } catch (_: IllegalArgumentException) { }
        }
        return null
    }

    private fun dec(value: String?): String = if (value == null) "" else URLDecoder.decode(value.replace("+", "%2B"), "UTF-8")

    /** URI parts; the fragment (name) may contain anything, so it is cut off before parsing. */
    private class Parts(link: String) {
        val name: String
        val user: String
        val host: String
        val port: Int
        val query: Map<String, String>

        init {
            val hash = link.indexOf('#')
            name = if (hash >= 0) dec(link.substring(hash + 1)) else ""
            val body = if (hash >= 0) link.substring(0, hash) else link
            val uri = URI(body.replace(" ", "%20"))
            user = dec(uri.rawUserInfo)
            host = (uri.host ?: "").removePrefix("[").removeSuffix("]")
            port = uri.port
            query = (uri.rawQuery ?: "").split("&").filter { it.contains("=") }
                .associate { it.substringBefore("=") to dec(it.substringAfter("=")) }
            require(host.isNotBlank() && port in 1..65535) { "bad address" }
        }

        fun q(key: String) = query[key].orEmpty()
    }

    private fun vless(link: String): Server {
        val p = Parts(link)
        val user = JSONObject().put("id", p.user).put("encryption", p.q("encryption").ifBlank { "none" })
        if (p.q("flow").isNotBlank()) user.put("flow", p.q("flow"))
        val settings = JSONObject().put("vnext", JSONArray().put(JSONObject().put("address", p.host).put("port", p.port).put("users", JSONArray().put(user))))
        return Server(p.name.ifBlank { p.host }, "vless", outbound("vless", settings, stream(p.query, p.q("type"), p.q("security"), p.host)), link)
    }

    private fun trojan(link: String): Server {
        val p = Parts(link)
        val settings = JSONObject().put("servers", JSONArray().put(JSONObject().put("address", p.host).put("port", p.port).put("password", p.user)))
        return Server(p.name.ifBlank { p.host }, "trojan", outbound("trojan", settings, stream(p.query, p.q("type"), p.q("security").ifBlank { "tls" }, p.host)), link)
    }

    private fun vmess(link: String): Server {
        val json = JSONObject(b64(link.substring("vmess://".length)) ?: error("bad vmess"))
        val user = JSONObject().put("id", json.optString("id")).put("alterId", json.optInt("aid", 0)).put("security", json.optString("scy").ifBlank { "auto" })
        val host = json.optString("add")
        val settings = JSONObject().put("vnext", JSONArray().put(JSONObject().put("address", host).put("port", json.optString("port").toInt()).put("users", JSONArray().put(user))))
        val params = mapOf("host" to json.optString("host"), "path" to json.optString("path"), "sni" to json.optString("sni"),
            "alpn" to json.optString("alpn"), "fp" to json.optString("fp"), "headerType" to json.optString("type"), "serviceName" to json.optString("path"))
        val s = stream(params, json.optString("net"), if (json.optString("tls") == "tls") "tls" else "none", host)
        return Server(json.optString("ps").ifBlank { host }, "vmess", outbound("vmess", settings, s), link)
    }

    private fun shadowsocks(link: String): Server {
        val hash = link.indexOf('#')
        val name = if (hash >= 0) dec(link.substring(hash + 1)) else ""
        val body = (if (hash >= 0) link.substring(0, hash) else link).removePrefix("ss://").substringBefore("?")
        val method: String
        val password: String
        val host: String
        val port: Int
        if (body.contains("@")) {
            val info = dec(body.substringBeforeLast("@"))
            val decoded = if (info.contains(":")) info else b64(info) ?: error("bad ss")
            method = decoded.substringBefore(":"); password = decoded.substringAfter(":")
            val address = body.substringAfterLast("@")
            host = address.substringBeforeLast(":").removePrefix("[").removeSuffix("]"); port = address.substringAfterLast(":").toInt()
        } else {
            val raw = b64(body) ?: error("bad ss")
            method = raw.substringBefore(":"); password = raw.substringAfter(":").substringBeforeLast("@")
            host = raw.substringAfterLast("@").substringBeforeLast(":"); port = raw.substringAfterLast(":").toInt()
        }
        require(host.isNotBlank() && port in 1..65535)
        val settings = JSONObject().put("servers", JSONArray().put(JSONObject().put("address", host).put("port", port).put("method", method).put("password", password)))
        return Server(name.ifBlank { host }, "shadowsocks", outbound("shadowsocks", settings, null), link)
    }

    private fun socks(link: String): Server {
        val p = Parts(link.replaceFirst(Regex("^socks5?://", RegexOption.IGNORE_CASE), "socks://"))
        val server = JSONObject().put("address", p.host).put("port", p.port)
        if (p.user.isNotBlank()) {
            val creds = if (p.user.contains(":")) p.user else b64(p.user) ?: p.user
            server.put("users", JSONArray().put(JSONObject().put("user", creds.substringBefore(":")).put("pass", creds.substringAfter(":"))))
        }
        return Server(p.name.ifBlank { p.host }, "socks", outbound("socks", JSONObject().put("servers", JSONArray().put(server)), null), link)
    }

    /**
     * hysteria2://<auth>@host:port?sni=…&insecure=1&alpn=h3#name → Xray «hysteria» (version 2). Salamander obfuscation
     * (obfs=salamander) is not supported by Xray's outbound in this form: such links are skipped, not half-built.
     */
    private fun hysteria2(link: String): Server {
        val p = Parts(link.replaceFirst(Regex("^hy2://", RegexOption.IGNORE_CASE), "hysteria2://"))
        require(p.q("obfs").isBlank()) { "obfs" }
        val tls = JSONObject().put("serverName", p.q("sni").ifBlank { p.host }).put("alpn", JSONArray(p.q("alpn").ifBlank { "h3" }.split(",")))
        if (p.q("insecure") == "1" || p.q("allowInsecure") == "1") tls.put("allowInsecure", true)
        if (p.q("pinSHA256").isNotBlank()) tls.put("pinnedPeerCertSha256", p.q("pinSHA256"))
        val stream = JSONObject().put("network", "hysteria").put("security", "tls").put("tlsSettings", tls)
            .put("hysteriaSettings", JSONObject().put("version", 2).put("auth", p.user))
        val settings = JSONObject().put("version", 2).put("address", p.host).put("port", p.port)
        return Server(p.name.ifBlank { p.host }, "hysteria", outbound("hysteria", settings, stream), link)
    }

    /** wireguard://<private key>@host:port?publickey=…&address=10.0.0.2/32,fd00::2/128&reserved=1,2,3&mtu=1280 */
    private fun wireguard(link: String): Server {
        val p = Parts(link.replaceFirst(Regex("^wg://", RegexOption.IGNORE_CASE), "wireguard://"))
        val peer = JSONObject().put("publicKey", p.q("publickey").ifBlank { p.q("publicKey") }).put("endpoint", "${p.host}:${p.port}")
            .put("allowedIPs", JSONArray(listOf("0.0.0.0/0", "::/0")))
        if (p.q("presharedkey").isNotBlank()) peer.put("preSharedKey", p.q("presharedkey"))
        val settings = JSONObject().put("secretKey", p.user).put("peers", JSONArray().put(peer))
            .put("address", JSONArray(p.q("address").ifBlank { "10.0.0.2/32" }.split(",").map { it.trim() }.filter { it.isNotBlank() }))
            .put("mtu", p.q("mtu").toIntOrNull() ?: 1280)
        p.q("reserved").takeIf { it.isNotBlank() }?.let { r -> settings.put("reserved", JSONArray(r.split(",").map { it.trim().toInt() })) }
        require(settings.getString("secretKey").isNotBlank() && peer.getString("publicKey").isNotBlank()) { "wireguard keys" }
        return Server(p.name.ifBlank { p.host }, "wireguard", outbound("wireguard", settings, null), link)
    }

    private fun outbound(protocol: String, settings: JSONObject, stream: JSONObject?): JSONObject {
        val row = JSONObject().put("protocol", protocol).put("settings", settings)
        if (stream != null) row.put("streamSettings", stream)
        return row
    }

    /** streamSettings: transport (tcp, ws, grpc, xhttp, httpupgrade) and security (tls, reality). */
    fun stream(p: Map<String, String>, rawNetwork: String, rawSecurity: String, host: String): JSONObject {
        val network = when (rawNetwork.ifBlank { "tcp" }) { "h2", "http", "splithttp" -> "xhttp"; else -> rawNetwork.ifBlank { "tcp" } }
        val stream = JSONObject().put("network", network)
        val path = p["path"].orEmpty()
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
                .apply { p["alpn"]?.takeIf { it.isNotBlank() }?.let { put("alpn", JSONArray(it.split(","))) } }
                .apply { if (p["allowInsecure"] == "1" || p["insecure"] == "1") put("allowInsecure", true) })
            "reality" -> stream.put("security", "reality").put("realitySettings", JSONObject().put("serverName", sni).put("fingerprint", fingerprint)
                .put("publicKey", p["pbk"].orEmpty()).put("shortId", p["sid"].orEmpty()).put("spiderX", p["spx"].orEmpty()))
            else -> stream.put("security", "none")
        }
        return stream
    }
}
