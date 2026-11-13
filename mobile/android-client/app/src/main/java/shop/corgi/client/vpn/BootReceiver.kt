package shop.corgi.client.vpn

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService
import shop.corgi.client.data.Store

/**
 * «Автоподключение при загрузке»: after a reboot (or an app update) the tunnel comes back if the user turned it on.
 * v1.9.7: after an automatic update it comes back if it was working when the update started.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in listOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED)) return
        val store = Store(context)
        UpdateJob.schedule(context)
        NetworkReceiver.sync(context)
        val s = store.settings
        if (intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            AppUpdateJob.schedule(context)
            // v1.9.7: the update was installed under a working VPN — it comes back at once.
            val prefs = context.getSharedPreferences(ApkInstaller.PREFS, Context.MODE_PRIVATE)
            val flagged = prefs.getBoolean(ApkInstaller.KEY_RESUME_VPN, false)
            prefs.edit().remove(ApkInstaller.KEY_RESUME_VPN).apply()
            val needsPermission = s.tunnelMode == "tun" && VpnService.prepare(context) != null
            if (store.active() != null && shop.corgi.client.core.ApkCheck.resumeAfterUpdate(flagged, needsPermission)) {
                ClientVpnService.start(context)
                return
            }
        }
        if (!s.autoConnectBoot || store.active() == null) return
        // Without the VPN permission nothing can start silently; «only proxy» needs none.
        if (s.tunnelMode == "tun" && VpnService.prepare(context) != null) return
        ClientVpnService.start(context)
    }
}
