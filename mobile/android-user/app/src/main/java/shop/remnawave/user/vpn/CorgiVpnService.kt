package shop.remnawave.user.vpn

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
import androidx.core.app.NotificationCompat
import shop.remnawave.user.MainActivity
import shop.remnawave.user.R
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * The embedded VPN («Встроенный VPN»): a VpnService tunnel driven by Xray-core (XrayEngine).
 *
 * Started with the subscription URL; the servers come from the subscription itself. The app's
 * own traffic and the apps the customer chose («Что работает без VPN») stay outside the tunnel.
 */
class CorgiVpnService : VpnService() {
    private var tun: ParcelFileDescriptor? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { shutdown(); return START_NOT_STICKY }
        val subscription = intent?.getStringExtra(EXTRA_SUBSCRIPTION).orEmpty()
        if (!XrayEngine.available() || !subscription.startsWith("https://")) { stopSelf(startId); return START_NOT_STICKY }
        foreground()
        state(this, STATE_CONNECTING)
        thread {
            try {
                val servers = ShareLinks.parseAll(fetch(subscription))
                if (servers.isEmpty()) throw IllegalStateException("no servers")
                val prefs = getSharedPreferences(PREFS, 0)
                prefs.edit().putString(KEY_SERVERS, servers.joinToString("\n") { it.name }).apply()
                val config = XrayEngine.config(servers, prefs.getString(KEY_SERVER, "").orEmpty(), prefs.getBoolean(KEY_BYPASS_RU, false))
                val builder = Builder().setSession(getString(R.string.app_name)).setMtu(MTU)
                    .addAddress("172.19.0.1", 30).addRoute("0.0.0.0", 0)
                    .addAddress("fdfe:dcba:9876::1", 126).addRoute("::", 0)
                    .addDnsServer("1.1.1.1")
                // Xray's own sockets must not loop into the tunnel: the app itself goes direct.
                builder.addDisallowedApplication(packageName)
                excludedApps(this).forEach { app -> try { builder.addDisallowedApplication(app) } catch (_: Exception) { } }
                if (Build.VERSION.SDK_INT >= 29) builder.setMetered(false)
                val fd = builder.establish() ?: throw IllegalStateException("VPN permission revoked")
                tun = fd
                XrayEngine.start(this, config, fd.fd) { state(this, STATE_OFF) }
                state(this, STATE_ON)
            } catch (exc: Exception) {
                getSharedPreferences(PREFS, 0).edit().putString(KEY_ERROR, exc.message ?: exc.javaClass.simpleName).apply()
                shutdown()
            }
        }
        return START_STICKY
    }

    override fun onRevoke() { shutdown() }

    override fun onDestroy() { shutdown(); super.onDestroy() }

    private fun shutdown() {
        XrayEngine.stop()
        try { tun?.close() } catch (_: Exception) { }
        tun = null
        state(this, STATE_OFF)
        if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_REMOVE) else @Suppress("DEPRECATION") stopForeground(true)
        stopSelf()
    }

    private fun fetch(url: String): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = true; connectTimeout = 15000; readTimeout = 15000
            // Remnawave answers v2ray clients with base64 share links.
            setRequestProperty("User-Agent", "v2rayNG/1.10.0 CorgiLusi")
        }
        if (connection.responseCode !in 200..299) throw IllegalStateException("subscription HTTP ${connection.responseCode}")
        return connection.inputStream.bufferedReader().use { it.readText() }
    }

    private fun foreground() {
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26 && manager?.getNotificationChannel(CHANNEL) == null)
            manager?.createNotificationChannel(NotificationChannel(CHANNEL, "VPN", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 2, Intent(this, CorgiVpnService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL).setSmallIcon(R.drawable.corgi_logo)
            .setContentTitle(getString(R.string.app_name)).setContentText("VPN").setOngoing(true).setContentIntent(open)
            .addAction(0, "Отключить", stop).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(7, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED)
        else startForeground(7, notification)
    }

    companion object {
        const val ACTION_START = "shop.corgi.vpn.START"
        const val ACTION_STOP = "shop.corgi.vpn.STOP"
        const val EXTRA_SUBSCRIPTION = "subscription"
        const val MTU = 1500
        const val CHANNEL = "corgi_vpn"
        const val PREFS = "shop_vpn"
        const val KEY_STATE = "state"
        const val KEY_ERROR = "error"
        const val KEY_SERVERS = "servers"
        const val KEY_SERVER = "server"
        const val KEY_BYPASS_RU = "bypass_ru"
        const val KEY_EXCLUDED = "excluded_apps"
        const val KEY_MODE = "mode"  // "engine" | "client"
        const val STATE_OFF = "off"
        const val STATE_CONNECTING = "connecting"
        const val STATE_ON = "on"

        private fun state(context: Context, value: String) {
            context.getSharedPreferences(PREFS, 0).edit().putString(KEY_STATE, value).apply()
            listeners.forEach { it(value) }
        }

        val listeners = mutableListOf<(String) -> Unit>()

        fun current(context: Context): String = context.getSharedPreferences(PREFS, 0).getString(KEY_STATE, STATE_OFF) ?: STATE_OFF

        fun excludedApps(context: Context): Set<String> =
            context.getSharedPreferences(PREFS, 0).getStringSet(KEY_EXCLUDED, emptySet()) ?: emptySet()

        fun servers(context: Context): List<String> =
            context.getSharedPreferences(PREFS, 0).getString(KEY_SERVERS, "").orEmpty().lines().filter { it.isNotBlank() }

        /** The built-in engine is used when the build has it and the customer did not choose a client app. */
        fun useEngine(context: Context): Boolean =
            XrayEngine.available() && context.getSharedPreferences(PREFS, 0).getString(KEY_MODE, "engine") == "engine"

        fun start(context: Context, subscription: String) {
            context.getSharedPreferences(PREFS, 0).edit().remove(KEY_ERROR).apply()
            val intent = Intent(context, CorgiVpnService::class.java).setAction(ACTION_START).putExtra(EXTRA_SUBSCRIPTION, subscription)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, CorgiVpnService::class.java).setAction(ACTION_STOP))
        }
    }
}
