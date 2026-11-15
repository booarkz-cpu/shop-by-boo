package shop.corgi.client.core

/**
 * v1.10.1: what «Экспорт логов» must not carry out of the phone. The core log names the servers, the keys of the
 * subscription and every site the person opened; the archive is meant for the support, so before a line is written
 * into it the secrets are masked:
 *
 * - links of the servers (vless://, vmess://, trojan://, ss://, hysteria2://, hy2://, tuic://, masque://) — fully;
 * - UUIDs (the keys of VLESS and VMess) — only the first four characters stay;
 * - addresses of the internet (IPv4 and IPv6) — the address goes, local ones (127.x, 10.x, 192.168.x…) stay;
 * - the place after «tcp:» / «udp:» in the core log (the server or the site) and the host of any https:// address;
 * - values of «password», «pass», «id», «key», «token», «uuid» fields.
 *
 * Line structure, times, levels and errors stay, so the log is still useful for finding a fault.
 */
object Redact {
    const val MASK = "•••"

    private val links =
        Regex("""\b(vless|vmess|trojan|ss|ssr|hysteria2|hy2|hysteria|tuic|masque|wireguard)://\S+""", RegexOption.IGNORE_CASE)
    private val uuid = Regex("""\b([0-9a-fA-F]{4})[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b""")
    private val fields = Regex(
        """(?i)((?<![A-Za-z0-9_])"?(?:password|pass|passwd|id|key|token|uuid|secret|auth)"?\s*[:=]\s*"?)([^"\s,;}&]+)"""
    )
    private val url = Regex("""\b(https?)://([^/\s:"']+)(:\d+)?([^\s"']*)""", RegexOption.IGNORE_CASE)
    private val target = Regex("""\b(tcp|udp):(\[[0-9a-fA-F:]+]|[^\s:]+):(\d+)""")
    private val ipv4 = Regex("""(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])""")

    // Full eight groups or a «::» form: «10:00:01» of a log time is not an address.
    private val ipv6 = Regex(
        """(?<![0-9a-fA-F:.])(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){1,6}:""" +
            """(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,5})?|::[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6})(?![0-9a-fA-F:])"""
    )

    /** True for an address that never leaves the phone or the home network. */
    fun local(ip: String): Boolean {
        val p = ip.split('.').mapNotNull { it.toIntOrNull() }
        if (p.size != 4 || p.any { it !in 0..255 }) return false
        return p[0] == 127 || p[0] == 10 || p[0] == 0 ||
            (p[0] == 192 && p[1] == 168) || (p[0] == 172 && p[1] in 16..31) ||
            (p[0] == 169 && p[1] == 254) || (p[0] == 100 && p[1] in 64..127) ||
            (p[0] == 198 && p[1] in 18..19)
    }

    fun line(text: String): String {
        var s = links.replace(text) { "${it.groupValues[1].lowercase()}://$MASK" }
        s = url.replace(s) { m ->
            val host = m.groupValues[2]
            val shown = if (local(host) || host == "localhost") host else MASK
            "${m.groupValues[1]}://$shown${m.groupValues[3]}" + if (m.groupValues[4].length > 1) "/$MASK" else m.groupValues[4]
        }
        s = target.replace(s) { m ->
            val host = m.groupValues[2]
            val shown = if (local(host) || host == "localhost") host else MASK
            "${m.groupValues[1]}:$shown:${m.groupValues[3]}"
        }
        s = uuid.replace(s) { "${it.groupValues[1]}$MASK" }
        s = fields.replace(s) { m -> if (m.groupValues[2] == MASK || m.groupValues[2].endsWith(MASK)) m.value else m.groupValues[1] + MASK }
        s = ipv4.replace(s) { m -> if (local(m.value)) m.value else MASK }
        s = ipv6.replace(s) { m -> if (m.value == "::1") m.value else MASK }
        return s
    }

    fun text(text: String): String = text.lineSequence().joinToString("\n") { line(it) }
}
