package shop.remnawave.user.vpn

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.Uri

/**
 * The «Подключить» button of the main screen.
 *
 * The app has no packet engine of its own (see CorgiVpnService): it hands the subscription to a
 * VPN client installed on the phone and shows whether a VPN is up. The first tap imports the
 * subscription into the client, later taps open the client to switch the tunnel on or off.
 * An embedded engine can replace [connect] later without touching the screens.
 */
object VpnClients {
    data class Client(val id: String, val title: String, val packageName: String, val store: String)

    val CLIENTS = listOf(
        Client("happ", "Happ", "com.happproxy", "https://play.google.com/store/apps/details?id=com.happproxy"),
        Client("v2rayng", "v2rayNG", "com.v2ray.ang", "https://play.google.com/store/apps/details?id=com.v2ray.ang"),
        Client("hiddify", "Hiddify", "app.hiddify.com", "https://play.google.com/store/apps/details?id=app.hiddify.com"),
    )

    /** Deep link that adds the subscription to a client; only https subscription URLs are passed on. */
    fun importLink(clientId: String, subscriptionUrl: String): String? {
        if (!subscriptionUrl.startsWith("https://") || subscriptionUrl.any { it.isWhitespace() }) return null
        val encoded = Uri.encode(subscriptionUrl)
        return when (clientId) {
            "happ" -> "happ://add/$encoded"
            "v2rayng" -> "v2rayng://install-sub?url=$encoded"
            "hiddify" -> "hiddify://import/$encoded"
            "streisand" -> "streisand://import/$encoded"
            else -> null
        }
    }

    fun installed(context: Context): List<Client> = CLIENTS.filter {
        context.packageManager.getLaunchIntentForPackage(it.packageName) != null
    }

    sealed class Result {
        object Imported : Result()
        object Opened : Result()
        object NoClient : Result()
        object NoSubscription : Result()
    }

    /** Import on the first tap for this subscription, then open the client. */
    fun connect(context: Context, subscriptionUrl: String): Result {
        if (!subscriptionUrl.startsWith("https://")) return Result.NoSubscription
        val prefs = context.getSharedPreferences("shop_vpn", 0)
        val clients = installed(context)
        val preferred = clients.firstOrNull { it.id == prefs.getString("client", "") } ?: clients.firstOrNull() ?: return Result.NoClient
        val marker = "imported:${preferred.id}:${subscriptionUrl.hashCode()}"
        if (!prefs.getBoolean(marker, false)) {
            val link = importLink(preferred.id, subscriptionUrl) ?: return Result.NoClient
            try {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                prefs.edit().putBoolean(marker, true).putString("client", preferred.id).apply()
                return Result.Imported
            } catch (_: ActivityNotFoundException) {
                // An old client without the deep link: fall through and just open it.
            }
        }
        val launch = context.packageManager.getLaunchIntentForPackage(preferred.packageName) ?: return Result.NoClient
        context.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return Result.Opened
    }

    /** Import into one named client (buttons «Добавить в Happ» and similar). */
    fun importInto(context: Context, clientId: String, subscriptionUrl: String): Boolean {
        val link = importLink(clientId, subscriptionUrl) ?: return false
        return try {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            context.getSharedPreferences("shop_vpn", 0).edit()
                .putBoolean("imported:$clientId:${subscriptionUrl.hashCode()}", true).putString("client", clientId).apply()
            true
        } catch (_: ActivityNotFoundException) {
            false
        }
    }

    fun vpnActive(context: Context): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return false
        @Suppress("DEPRECATION")
        return cm.allNetworks.any { cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true }
    }

    /** Calls [onChange] whenever a VPN network appears or disappears. Returns the unregister function. */
    fun watch(context: Context, onChange: (Boolean) -> Unit): () -> Unit {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return {}
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_VPN)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = onChange(true)
            override fun onLost(network: Network) = onChange(vpnActive(context))
        }
        val unregister: () -> Unit = {
            try { cm.unregisterNetworkCallback(callback) } catch (_: Exception) { }
        }
        return try {
            cm.registerNetworkCallback(request, callback)
            onChange(vpnActive(context))
            unregister
        } catch (_: Exception) {
            val nothing: () -> Unit = {}
            nothing
        }
    }
}
