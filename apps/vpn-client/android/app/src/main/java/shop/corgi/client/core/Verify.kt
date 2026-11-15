package shop.corgi.client.core

/**
 * v1.10.0: «подключён» only after the tunnel answered. After the core starts, a page is asked through the tunnel:
 * until it answers the state is «checking» (shown as connecting); no answer for [WARN_MS] — «no_answer»: the VPN
 * stays up, the screen warns that the server is silent, the check goes on and the first answer makes it «on».
 */
object Verify {
    const val CHECKING = "checking"
    const val NO_ANSWER = "no_answer"
    const val ON = "on"
    const val WARN_MS = 15_000L
    const val FAST_MS = 1_500L
    const val SLOW_MS = 5_000L

    /** The state to show after a check that [answered] or not, [sinceStartMs] after the core started. */
    fun state(answered: Boolean, sinceStartMs: Long): String = when {
        answered -> ON
        sinceStartMs >= WARN_MS -> NO_ANSWER
        else -> CHECKING
    }

    /** The pause before the next check: often at first, rarely once the warning is shown. */
    fun pause(sinceStartMs: Long): Long = if (sinceStartMs >= WARN_MS) SLOW_MS else FAST_MS
}
