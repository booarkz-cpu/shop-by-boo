package shop.corgi.client.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import shop.corgi.client.R
import shop.corgi.client.core.ConfigBuilder
import shop.corgi.client.data.Store
import shop.corgi.client.engine.Xray
import shop.corgi.client.ui.MainActivity
import kotlin.concurrent.thread

/** The tunnel: VpnService + Xray-core with the active profile's config; apps included or left out as the user chose. */
class ClientVpnService : VpnService() {
    private var tun: ParcelFileDescriptor? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { shutdown(); return START_NOT_STICKY }
        if (!Xray.available()) { error(this, "В этой сборке нет движка Xray"); stopSelf(startId); return START_NOT_STICKY }
        foreground()
        state(this, STATE_CONNECTING)
        thread {
            try {
                val store = Store(this)
                val profile = store.active() ?: throw IllegalStateException("Добавьте подписку или сервер")
                val s = store.settings
                val config = if (profile.kind == "json") ConfigBuilder.fromJson(profile.json, s)
                    else ConfigBuilder.build(profile.servers(), store.activeServer, s, store.geoReady())
                if (ConfigBuilder.needsGeo(config) && !store.geoReady()) throw IllegalStateException("Нужны geo-файлы: «Маршруты → Скачать geo-файлы»")
                val builder = Builder().setSession(getString(R.string.app_name)).setMtu(s.mtu)
                    .addAddress("172.19.0.1", 30).addRoute("0.0.0.0", 0).addDnsServer(s.dns.firstOrNull { !it.contains("/") } ?: "1.1.1.1")
                if (s.ipv6) builder.addAddress("fdfe:dcba:9876::1", 126).addRoute("::", 0)
                when (if (s.appsMode == "only" && s.apps.none { it != packageName }) "all" else s.appsMode) {
                    // Only the chosen apps go through the tunnel (this app is never one of them).
                    "only" -> s.apps.filter { it != packageName }.forEach { app -> runCatching { builder.addAllowedApplication(app) } }
                    // Xray's own sockets must not loop into the tunnel: the app itself always goes direct.
                    else -> {
                        builder.addDisallowedApplication(packageName)
                        if (s.appsMode == "except") s.apps.forEach { app -> runCatching { builder.addDisallowedApplication(app) } }
                    }
                }
                if (Build.VERSION.SDK_INT >= 29) builder.setMetered(false)
                val fd = builder.establish() ?: throw IllegalStateException("Нет разрешения на VPN")
                tun = fd
                Xray.start(this, config, fd.fd) { state(this, STATE_OFF) }
                state(this, STATE_ON)
                QuickTile.refresh(this)
            } catch (exc: Exception) {
                error(this, exc.message ?: exc.javaClass.simpleName)
                shutdown()
            }
        }
        return START_STICKY
    }

    override fun onRevoke() { shutdown() }

    override fun onDestroy() { shutdown(); super.onDestroy() }

    private fun shutdown() {
        Xray.stop()
        try { tun?.close() } catch (_: Exception) { }
        tun = null
        state(this, STATE_OFF)
        QuickTile.refresh(this)
        if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_REMOVE) else @Suppress("DEPRECATION") stopForeground(true)
        stopSelf()
    }

    private fun foreground() {
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26 && manager?.getNotificationChannel(CHANNEL) == null)
            manager?.createNotificationChannel(NotificationChannel(CHANNEL, "VPN", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 2, Intent(this, ClientVpnService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(this)
        val notification = builder.setSmallIcon(R.drawable.corgi_logo).setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.connected)).setOngoing(true).setContentIntent(open)
            .addAction(Notification.Action.Builder(null, getString(R.string.disconnect), stop).build()).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(7, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED)
        else startForeground(7, notification)
    }

    companion object {
        const val ACTION_START = "shop.corgi.client.START"
        const val ACTION_STOP = "shop.corgi.client.STOP"
        const val CHANNEL = "corgi_client_vpn"
        const val STATE_OFF = "off"
        const val STATE_CONNECTING = "connecting"
        const val STATE_ON = "on"
        val listeners = mutableListOf<(String) -> Unit>()

        private fun prefs(context: Context) = context.getSharedPreferences("client_vpn", 0)

        private fun state(context: Context, value: String) {
            prefs(context).edit().putString("state", value).apply()
            listeners.toList().forEach { it(value) }
        }

        private fun error(context: Context, value: String) { prefs(context).edit().putString("error", value).apply() }

        fun current(context: Context): String = prefs(context).getString("state", STATE_OFF) ?: STATE_OFF

        fun lastError(context: Context): String = prefs(context).getString("error", "").orEmpty()

        fun start(context: Context) {
            prefs(context).edit().remove("error").apply()
            val intent = Intent(context, ClientVpnService::class.java).setAction(ACTION_START)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
        }

        fun stop(context: Context) { context.startService(Intent(context, ClientVpnService::class.java).setAction(ACTION_STOP)) }
    }
}
