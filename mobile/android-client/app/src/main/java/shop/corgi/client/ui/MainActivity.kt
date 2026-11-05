package shop.corgi.client.ui

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import shop.corgi.client.data.Store
import shop.corgi.client.vpn.ClientVpnService
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {
    private val permission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (VpnService.prepare(this) == null) ClientVpnService.start(this)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = Store(this)
        thread { runCatching { store.updateDue() } }
        val incoming = importText(intent)
        ciHook(intent)
        setIntent(Intent())  // handled once: a recreation must not import or connect again
        setContent { ClientApp(store, incoming, ::connect) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        ciHook(intent)
        val text = importText(intent)
        setIntent(Intent())
        if (text != null) { runCatching { Store(this).add(text) }; recreate() }
    }

    /** Asks for the VPN permission the first time, then starts the tunnel. */
    fun connect() {
        val ask = VpnService.prepare(this)
        if (ask != null) permission.launch(ask) else ClientVpnService.start(this)
    }

    /** A link or text shared to the app, a vless:// … link opened from the browser, or corgiclient://import?url=… */
    private fun importText(intent: Intent?): String? = when (intent?.action) {
        Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)
        Intent.ACTION_VIEW -> intent.data?.let { uri -> if (uri.scheme == "corgiclient") uri.getQueryParameter("url") else uri.toString() }
        else -> null
    }

    /** CI only (debuggable builds, scripts/mobile/client-vpn-e2e.sh): import a subscription, connect, disconnect. */
    private fun ciHook(intent: Intent?) {
        if (intent == null || (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) == 0) return
        val store = Store(this)
        intent.getStringExtra("client_test_import")?.let { url ->
            thread {
                runCatching {
                    store.profiles.forEach { store.remove(it.id) }
                    val profile = store.add(url)
                    store.activeProfile = profile.id
                    store.update(profile)
                    if (intent.getBooleanExtra("client_test_connect", false)) runOnUiThread { connect() }
                }.onFailure { getSharedPreferences("client_vpn", 0).edit().putString("error", it.message ?: "import").apply() }
            }
        }
        if (intent.getBooleanExtra("client_test_stop", false)) ClientVpnService.stop(this)
    }
}
