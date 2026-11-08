package shop.corgi.client.vpn

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.VpnService
import shop.corgi.client.core.Logs
import shop.corgi.client.core.TrustedNetworks
import shop.corgi.client.data.Store

/**
 * v1.6.0 (N10): «Подключаться при смене сети» — the system wakes this receiver when a network with the internet
 * appears (Wi-Fi or mobile), even when the app is not running; the tunnel starts if it is off, a server is chosen and
 * the VPN permission was granted before. Android may refuse to start it from the background: then nothing breaks.
 */
class NetworkReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val store = Store(context)
        val s = store.settings
        // v1.7.2 (N12): «Доверенные Wi-Fi» — pause at home, back on any other network (only after its own pause).
        if (s.trustedWifi.isNotEmpty()) {
            val prefs = context.getSharedPreferences("client_vpn", 0)
            val on = ClientVpnService.current(context) != "off"
            when (TrustedNetworks.decide(currentSsid(context), s.trustedWifi, on, prefs.getBoolean(PAUSED, false))) {
                TrustedNetworks.Action.PAUSE -> {
                    prefs.edit().putBoolean(PAUSED, true).apply()
                    Logs(context.filesDir).app("[VPN] paused on a trusted Wi-Fi")
                    ClientVpnService.stop(context)
                    return
                }
                TrustedNetworks.Action.RESUME -> {
                    prefs.edit().putBoolean(PAUSED, false).apply()
                    if (store.active() == null || store.mustChoose) return
                    if (s.tunnelMode == "tun" && VpnService.prepare(context) != null) return
                    Logs(context.filesDir).app("[VPN] back on after a trusted Wi-Fi")
                    runCatching { ClientVpnService.start(context) }
                    return
                }
                TrustedNetworks.Action.NONE -> if (currentSsid(context)?.let { it in s.trustedWifi } == true) return
            }
        }
        if (!s.autoConnectNetwork || store.active() == null || store.mustChoose) return
        if (ClientVpnService.current(context) != "off") return
        if (s.tunnelMode == "tun" && VpnService.prepare(context) != null) return
        runCatching { ClientVpnService.start(context) }
    }

    companion object {
        private const val PAUSED = "paused_trusted"

        /** The Wi-Fi now (null on mobile data, or without the location permission Android asks for the name). */
        @Suppress("DEPRECATION")
        fun currentSsid(context: Context): String? {
            val cm = context.getSystemService(ConnectivityManager::class.java) ?: return null
            val wifi = cm.allNetworks.any { n -> cm.getNetworkCapabilities(n)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true }
            if (!wifi) return null
            val manager = context.applicationContext.getSystemService(android.net.wifi.WifiManager::class.java) ?: return null
            return TrustedNetworks.clean(runCatching { manager.connectionInfo?.ssid }.getOrNull())
        }

        /** The user switched the tunnel off or on by hand: a pause of «Доверенные Wi-Fi» no longer stands. */
        fun forgetPause(context: Context) {
            context.getSharedPreferences("client_vpn", 0).edit().remove(PAUSED).apply()
        }

        private fun pending(context: Context): PendingIntent = PendingIntent.getBroadcast(
            context,
            7,
            Intent(context, NetworkReceiver::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        )

        /** Registers or unregisters the callback by the setting (called when it changes and after a reboot). */
        fun sync(context: Context) {
            val cm = context.getSystemService(ConnectivityManager::class.java) ?: return
            runCatching { cm.unregisterNetworkCallback(pending(context)) }
            val s = Store(context).settings
            if (!s.autoConnectNetwork && s.trustedWifi.isEmpty()) return
            val request =
                NetworkRequest.Builder()
                    .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                    .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                    .build()
            runCatching { cm.registerNetworkCallback(request, pending(context)) }
        }
    }
}
