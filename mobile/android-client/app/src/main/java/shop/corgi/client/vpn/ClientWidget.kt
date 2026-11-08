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

        /** True when at least one widget is on the home screen (the speed is pushed only then). */
        fun present(context: Context): Boolean =
            AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context, ClientWidget::class.java)).isNotEmpty()

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
            // v1.8.2 (N12): the mascot for the state and the speed while connected.
            val state = ClientVpnService.current(context)
            views.setImageViewResource(R.id.widget_mascot, when (state) {
                ClientVpnService.STATE_ON -> R.drawable.mascot_happy
                ClientVpnService.STATE_CONNECTING -> R.drawable.mascot_run
                else -> R.drawable.mascot_sleep
            })
            val session = ClientVpnService.session
            views.setTextViewText(R.id.widget_speed, if (state == ClientVpnService.STATE_ON)
                "↓ ${shop.corgi.client.core.SubInfo.bytes(session.downSpeed)}/s  ↑ ${shop.corgi.client.core.SubInfo.bytes(session.upSpeed)}/s" else "")
            val toggle = PendingIntent.getBroadcast(context, 11, Intent(context, ClientWidget::class.java).setAction(ACTION_TOGGLE),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            views.setOnClickPendingIntent(R.id.widget_root, toggle)
            manager.updateAppWidget(ids, views)
        }
    }
}
