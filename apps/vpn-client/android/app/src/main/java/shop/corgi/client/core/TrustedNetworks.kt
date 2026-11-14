package shop.corgi.client.core

/**
 * v1.7.2 (N12, phase 2): «Доверенные Wi-Fi». On a trusted network (the home Wi-Fi) the tunnel pauses; on any other
 * network — mobile data or another Wi-Fi — it comes back at once, but only if it was this feature that paused it.
 */
object TrustedNetworks {
    enum class Action { PAUSE, RESUME, NONE }

    const val MAX = 20

    /** The SSID as Android gives it — in quotes, or «<unknown ssid>» without the location permission — made plain. */
    fun clean(raw: String?): String? {
        val s = raw?.trim()?.removeSurrounding("\"")?.trim().orEmpty()
        return s.takeIf { it.isNotEmpty() && it != "<unknown ssid>" && it.length <= 32 }
    }

    fun valid(ssid: String): Boolean = ssid.isNotBlank() && ssid.length <= 32 && ssid.none { it == '\n' || it == '\r' }

    /**
     * [ssid] — the Wi-Fi now (null on mobile data or when unknown), [vpnOn] — the tunnel is up or connecting,
     * [pausedByUs] — it was paused by this feature, not switched off by the user.
     */
    fun decide(ssid: String?, trusted: List<String>, vpnOn: Boolean, pausedByUs: Boolean): Action {
        if (trusted.isEmpty()) return Action.NONE
        val home = ssid != null && trusted.any { it == ssid }
        return when {
            home && vpnOn -> Action.PAUSE
            !home && !vpnOn && pausedByUs -> Action.RESUME
            else -> Action.NONE
        }
    }
}
