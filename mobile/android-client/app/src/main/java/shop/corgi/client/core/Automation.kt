package shop.corgi.client.core

/**
 * v1.8.0 (N12, phase 3): Intents for Tasker, MacroDroid and other automation apps — broadcasts
 * `shop.corgi.client.action.CONNECT`, `…DISCONNECT`, `…TOGGLE` (with an optional `server` extra — the index in the
 * current provider). Off by default: any app on the phone could send them, so the user turns them on.
 */
object Automation {
    const val CONNECT = "shop.corgi.client.action.CONNECT"
    const val DISCONNECT = "shop.corgi.client.action.DISCONNECT"
    const val TOGGLE = "shop.corgi.client.action.TOGGLE"
    const val EXTRA_SERVER = "server"

    enum class Step { START, STOP, NOTHING }

    fun decide(action: String?, allowed: Boolean, running: Boolean): Step {
        if (!allowed) return Step.NOTHING
        return when (action) {
            CONNECT -> if (running) Step.NOTHING else Step.START
            DISCONNECT -> if (running) Step.STOP else Step.NOTHING
            TOGGLE -> if (running) Step.STOP else Step.START
            else -> Step.NOTHING
        }
    }

    /** The server asked for, as the store keeps it, or null when it is missing or not in [count]. */
    fun server(extra: Int?, count: Int): String? = extra?.takeIf { it in 0 until count }?.toString()
}
