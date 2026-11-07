package shop.corgi.client.vpn

/** The traffic of one VPN session: when it began (0 — no session), bytes of the last second and since the start. */
data class Session(
    val startedAt: Long = 0L,
    val upSpeed: Long = 0L,
    val downSpeed: Long = 0L,
    val upTotal: Long = 0L,
    val downTotal: Long = 0L
) {
    /** The next second of the session: [up] and [down] bytes went through the proxy since the previous one. */
    fun add(up: Long, down: Long): Session = copy(upSpeed = up, downSpeed = down, upTotal = upTotal + up, downTotal = downTotal + down)

    /** Whole seconds since the start at [now]; 0 without a session. */
    fun seconds(now: Long): Long = if (startedAt == 0L) 0L else ((now - startedAt) / 1000L).coerceAtLeast(0L)
}
