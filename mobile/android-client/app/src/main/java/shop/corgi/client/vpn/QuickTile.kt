package shop.corgi.client.vpn

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import shop.corgi.client.ui.MainActivity

/** The quick settings tile: one tap connects or disconnects (the first time, the app asks for the VPN permission). */
class QuickTile : TileService() {
    override fun onStartListening() { paint() }

    override fun onClick() {
        if (ClientVpnService.current(this) == ClientVpnService.STATE_OFF) {
            if (VpnService.prepare(this) != null) {
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
        tile.state = if (ClientVpnService.current(this) == ClientVpnService.STATE_OFF) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE
        tile.updateTile()
    }

    companion object {
        fun refresh(context: Context) {
            runCatching { requestListeningState(context, ComponentName(context, QuickTile::class.java)) }
        }
    }
}
