package shop.corgi.client.vpn

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService
import shop.corgi.client.data.Store

/** «Автоподключение при загрузке»: after a reboot (or an app update) the tunnel comes back if the user turned it on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in listOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED)) return
        val store = Store(context)
        UpdateJob.schedule(context)
        NetworkReceiver.sync(context)
        val s = store.settings
        if (!s.autoConnectBoot || store.active() == null) return
        // Without the VPN permission nothing can start silently; «only proxy» needs none.
        if (s.tunnelMode == "tun" && VpnService.prepare(context) != null) return
        ClientVpnService.start(context)
    }
}
