package shop.corgi.client.vpn

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.VpnService
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
        if (!s.autoConnectNetwork || store.active() == null || store.mustChoose) return
        if (ClientVpnService.current(context) != "off") return
        if (s.tunnelMode == "tun" && VpnService.prepare(context) != null) return
        runCatching { ClientVpnService.start(context) }
    }

    companion object {
        private fun pending(context: Context): PendingIntent =
            PendingIntent.getBroadcast(
                context, 7, Intent(context, NetworkReceiver::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
            )

        /** Registers or unregisters the callback by the setting (called when it changes and after a reboot). */
        fun sync(context: Context) {
            val cm = context.getSystemService(ConnectivityManager::class.java) ?: return
            runCatching { cm.unregisterNetworkCallback(pending(context)) }
            if (!Store(context).settings.autoConnectNetwork) return
            val request =
                NetworkRequest.Builder()
                    .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                    .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                    .build()
            runCatching { cm.registerNetworkCallback(request, pending(context)) }
        }
    }
}
