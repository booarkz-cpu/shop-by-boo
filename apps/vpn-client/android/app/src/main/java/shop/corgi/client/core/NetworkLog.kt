package shop.corgi.client.core

/**
 * v1.7.4 (N12, phase 2): «Журнал сети» — what the device connects to and where it goes, live. Xray's access log (on
 * only while the switch is on) has a line per connection: «… accepted tcp:example.com:443 [tun-in -> proxy-0]»; with
 * sniffing it carries the domain. The route tells: through the VPN, direct, blocked or the DNS module.
 */
object NetworkLog {
    enum class Route { PROXY, DIRECT, BLOCK, DNS }

    data class Entry(val time: String, val network: String, val host: String, val port: Int, val route: Route, val outbound: String)

    private val LINE = Regex(
        """^(\d{4}/\d{2}/\d{2} (\d{2}:\d{2}:\d{2}))\S*\s+from\s+\S+\s+accepted\s+(tcp|udp):(\[[0-9a-fA-F:]+]|[^\s:]+):(\d{1,5})\s+\[([\w.-]+)\s+(?:->|>>)\s+([\w.-]+)]"""
    )

    fun route(outbound: String): Route = when {
        outbound == "block" -> Route.BLOCK
        outbound == "direct" -> Route.DIRECT
        outbound == "dns-out" -> Route.DNS
        else -> Route.PROXY
    }

    /** One line of the access log, or null for anything else (DNS answers, errors, junk). */
    fun parse(line: String): Entry? {
        val m = LINE.find(line.trim()) ?: return null
        val (_, time, network, host, port, _, outbound) = m.destructured
        val p = port.toIntOrNull()?.takeIf { it in 1..65535 } ?: return null
        return Entry(time, network, host.removePrefix("[").removeSuffix("]"), p, route(outbound), outbound)
    }

    /** The newest [limit] entries first, only [route] when given, only hosts containing [query]. */
    fun entries(lines: List<String>, route: Route? = null, query: String = "", limit: Int = 300): List<Entry> {
        val q = query.trim().lowercase()
        return lines.asReversed().asSequence().mapNotNull { parse(it) }
            .filter { route == null || it.route == route }
            .filter { q.isEmpty() || it.host.lowercase().contains(q) }
            .take(limit).toList()
    }
}
