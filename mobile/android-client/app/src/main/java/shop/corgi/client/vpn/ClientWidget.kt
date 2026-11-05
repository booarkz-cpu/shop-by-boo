package shop.corgi.client.vpn

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.widget.RemoteViews
import shop.corgi.client.R
import shop.corgi.client.core.ConfigBuilder
import shop.corgi.client.data.Store
import shop.corgi.client.ui.MainActivity

/** The home-screen widget: «VPN подключён» / «VPN выключен», the active server; a tap toggles the tunnel. */
class ClientWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) { paint(context, manager, ids) }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action != ACTION_TOGGLE) return
        if (ClientVpnService.current(context) != ClientVpnService.STATE_OFF) ClientVpnService.stop(context)
        else if (VpnService.prepare(context) != null) {
            // The first time Android asks for the VPN permission: that needs the app on screen.
            context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } else ClientVpnService.start(context)
    }

    companion object {
        const val ACTION_TOGGLE = "shop.corgi.client.WIDGET_TOGGLE"

        fun refresh(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, ClientWidget::class.java))
            if (ids.isNotEmpty()) paint(context, manager, ids)
        }

        private fun paint(context: Context, manager: AppWidgetManager, ids: IntArray) {
            val views = RemoteViews(context.packageName, R.layout.client_widget)
            views.setTextViewText(R.id.widget_state, context.getString(when (ClientVpnService.current(context)) {
                ClientVpnService.STATE_ON -> R.string.connected
                ClientVpnService.STATE_CONNECTING -> R.string.vpn_connecting
                else -> R.string.vpn_off
            }))
            val store = Store(context)
            val profile = store.active()
            val server = when {
                profile == null -> ""
                profile.kind == "json" || store.activeServer == ConfigBuilder.AUTO -> profile.name
                else -> profile.servers().getOrNull(store.activeServer.toIntOrNull() ?: -1)?.name ?: profile.name
            }
            views.setTextViewText(R.id.widget_server, server)
            val toggle = PendingIntent.getBroadcast(context, 11, Intent(context, ClientWidget::class.java).setAction(ACTION_TOGGLE),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            views.setOnClickPendingIntent(R.id.widget_root, toggle)
            manager.updateAppWidget(ids, views)
        }
    }
}
