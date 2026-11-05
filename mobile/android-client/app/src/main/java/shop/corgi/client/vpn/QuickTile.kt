package shop.corgi.client.vpn

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import shop.corgi.client.data.Store
import shop.corgi.client.ui.MainActivity

/** The quick settings tile: one tap connects or disconnects (the first time, the app asks for the VPN permission). */
class QuickTile : TileService() {
    override fun onStartListening() { paint() }

    @android.annotation.SuppressLint("StartActivityAndCollapseDeprecated")  // the Intent form only below Android 14
    override fun onClick() {
        if (ClientVpnService.current(this) == ClientVpnService.STATE_OFF) {
            if (Store(this).settings.tunnelMode == "tun" && VpnService.prepare(this) != null) {
                val intent = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                if (Build.VERSION.SDK_INT >= 34) {
                    startActivityAndCollapse(android.app.PendingIntent.getActivity(this, 3, intent, android.app.PendingIntent.FLAG_IMMUTABLE))
                } else @Suppress("DEPRECATION") startActivityAndCollapse(intent)
                return
            }
            ClientVpnService.start(this)
        } else ClientVpnService.stop(this)
        paint()
    }

    private fun paint() {
        val tile = qsTile ?: return
        val state = ClientVpnService.current(this)
        tile.state = if (state == ClientVpnService.STATE_OFF) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE
        // «Сервер и статус»: the tile says where it connects (Android 10+), else only the app's name.
        if (Build.VERSION.SDK_INT >= 29) tile.subtitle = runCatching {
            val store = Store(this)
            if (!store.settings.tileDetails) null else {
                val p = store.active()
                val server = p?.servers()?.getOrNull(store.activeServer.toIntOrNull() ?: -1)?.name ?: p?.title
                listOfNotNull(if (state == ClientVpnService.STATE_ON) "●" else null, server).joinToString(" ").ifBlank { null }
            }
        }.getOrNull()
        tile.updateTile()
    }

    companion object {
        fun refresh(context: Context) {
            runCatching { requestListeningState(context, ComponentName(context, QuickTile::class.java)) }
        }
    }
}
