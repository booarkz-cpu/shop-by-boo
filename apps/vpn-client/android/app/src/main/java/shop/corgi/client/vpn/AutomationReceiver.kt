package shop.corgi.client.vpn

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService
import shop.corgi.client.core.Automation
import shop.corgi.client.core.Logs
import shop.corgi.client.data.Store

/**
 * v1.8.0 (N12, phase 3): connect, disconnect or toggle from Tasker and other automation apps — only while
 * «Разрешить управление другим приложениям» is on. Connecting needs the VPN permission granted in the app before;
 * Android may refuse to start the tunnel from the background, then the app's log says so.
 */
class AutomationReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val store = Store(context)
        val running = ClientVpnService.current(context) != ClientVpnService.STATE_OFF
        val step = Automation.decide(intent.action, store.settings.allowAutomation, running)
        val logs = Logs(context.filesDir)
        when (step) {
            Automation.Step.NOTHING -> return
            Automation.Step.STOP -> {
                logs.app("[VPN] stop by ${intent.action}")
                ClientVpnService.stop(context)
            }
            Automation.Step.START -> {
                val count = store.active()?.servers()?.size ?: 0
                val extra = if (intent.hasExtra(Automation.EXTRA_SERVER)) intent.getIntExtra(Automation.EXTRA_SERVER, -1) else null
                Automation.server(extra, count)?.let { store.activeServer = it }
                if (store.active() == null || store.mustChoose) return
                if (store.settings.tunnelMode == "tun" && VpnService.prepare(context) != null) {
                    logs.app("[VPN] ${intent.action}: no VPN permission yet — open the app once")
                    return
                }
                logs.app("[VPN] start by ${intent.action}")
                runCatching { ClientVpnService.start(context) }.onFailure { logs.app("[VPN] start refused: $it") }
            }
        }
    }
}
