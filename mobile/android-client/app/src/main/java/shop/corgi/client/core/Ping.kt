package shop.corgi.client.core

import org.json.JSONArray
import org.json.JSONObject
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Server delays by the method chosen in «Пинг»: through the Xray core (an HTTP request to the test URL through the
 * server — the real delay), a TCP connect to the server's port, or ICMP ping of its address. -1 — no answer in time.
 */
object Ping {
    /** The key a delay is kept under: the share link, or for a JSON config its name and address (indexes repeat between providers). */
    fun key(server: Server): String = if (server.link.startsWith("config:"))
        "config:${server.name}@" + runCatching { "${server.host}:${server.port}" }.getOrDefault("") else server.link

    /** The config a core probe runs: the server's outbound alone (the probe goes through the first outbound). */
    fun probeConfig(server: Server): String = JSONObject()
        .put("log", JSONObject().put("loglevel", "none"))
        .put("outbounds", JSONArray().put(JSONObject(server.outbound.toString()).put("tag", "proxy"))
            .put(JSONObject().put("tag", "direct").put("protocol", "freedom")))
        .toString()

    fun tcp(host: String, port: Int, timeoutMs: Int): Int = try {
        val start = System.nanoTime()
        Socket().use { it.connect(InetSocketAddress(host, port), timeoutMs) }
        ((System.nanoTime() - start) / 1_000_000).toInt()
    } catch (_: Exception) { -1 }

    /** ICMP with the system ping (no root needed); the time from its «time=…» line. */
    fun icmp(host: String, timeoutSec: Int): Int = try {
        require(Regex("^[A-Za-z0-9.:-]{1,253}$").matches(host)) { "host" }
        val process = ProcessBuilder("/system/bin/ping", "-c", "1", "-W", timeoutSec.toString(), host).redirectErrorStream(true).start()
        val out = process.inputStream.bufferedReader().use { it.readText() }
        process.waitFor(timeoutSec + 2L, TimeUnit.SECONDS)
        parseIcmp(out)
    } catch (_: Exception) { -1 }

    fun parseIcmp(out: String): Int = Regex("time[=<]([0-9.]+) ?ms").find(out)?.groupValues?.get(1)?.toDoubleOrNull()?.toInt()?.coerceAtLeast(1) ?: -1

    /** All servers, four at a time; ``core`` measures one server through the engine. */
    fun all(servers: List<Server>, s: Settings, core: (Server) -> Long): Map<String, Int> {
        val pool = Executors.newFixedThreadPool(4)
        try {
            val jobs = servers.associate { server ->
                key(server) to pool.submit(Callable {
                    runCatching {
                        when (s.pingMethod) {
                            "tcp" -> tcp(server.host, server.port, s.pingTimeout * 1000)
                            "icmp" -> icmp(server.host, s.pingTimeout)
                            else -> core(server).toInt()
                        }
                    }.getOrDefault(-1)
                })
            }
            return jobs.mapValues { (_, job) -> runCatching { job.get(s.pingTimeout + 3L, TimeUnit.SECONDS) }.getOrDefault(-1)
                .let { if (it > s.pingTimeout * 1000) -1 else it } }
        } finally { pool.shutdownNow() }
    }

    /** Green under 300 ms, yellow under 800 ms, red above or without an answer. */
    fun level(ms: Int?): Int = when { ms == null -> 0; ms < 0 -> 3; ms < 300 -> 1; ms < 800 -> 2; else -> 3 }
}

/** Server list order and filter (search text and protocol chip), as in «Серверы». */
object ServerList {
    fun arrange(servers: List<Server>, sort: String, pings: Map<String, Int>, query: String, family: String?): List<Pair<Int, Server>> {
        val q = query.trim().lowercase()
        val indexed = servers.mapIndexed { i, s -> i to s }.filter { (_, s) ->
            (q.isEmpty() || s.name.lowercase().contains(q) || s.host.lowercase().contains(q)) && (family == null || s.family == family)
        }
        return when (sort) {
            "name" -> indexed.sortedBy { it.second.name.lowercase() }
            "ping" -> indexed.sortedBy { (_, s) -> pings[Ping.key(s)]?.takeIf { it >= 0 } ?: Int.MAX_VALUE }
            else -> indexed
        }
    }
}
