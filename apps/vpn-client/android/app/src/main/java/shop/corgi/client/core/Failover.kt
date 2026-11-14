package shop.corgi.client.core

/**
 * v1.7.1 (N12, phase 2): Smart Failover. While connected, the tunnel is probed every [PROBE_MS]; when the chosen server
 * has not answered for [timeoutMs] in a row, the tunnel switches to the fastest other server of the provider (the
 * pings measured last), without the user. «Auto» needs none of this: its balancer already leaves a dead server.
 */
class Failover(private val timeoutMs: Long) {
    private var failingSince: Long? = null

    /** One probe's result; true when it is time to switch (then the count starts over). */
    fun record(ok: Boolean, now: Long): Boolean {
        if (ok) {
            failingSince = null
            return false
        }
        val since = failingSince ?: now.also { failingSince = it }
        if (now - since < timeoutMs) return false
        failingSince = null
        return true
    }

    companion object {
        const val PROBE_MS = 10_000L

        /**
         * The server to switch to: the lowest known ping among the others (a failed ping — negative — last), and the next
         * one in the list when nothing was measured; null when there is no other server or the choice is «auto».
         */
        fun next(keys: List<String>, current: String, pings: Map<String, Int>): String? {
            if (current == ConfigBuilder.AUTO || keys.size < 2) return null
            val now = current.toIntOrNull() ?: return null
            val others = keys.indices.filter { it != now }
            val measured = others.filter { (pings[keys[it]] ?: -1) >= 0 }
            val best = measured.minByOrNull { pings[keys[it]]!! } ?: others.firstOrNull { it > now } ?: others.first()
            return best.toString()
        }
    }
}
