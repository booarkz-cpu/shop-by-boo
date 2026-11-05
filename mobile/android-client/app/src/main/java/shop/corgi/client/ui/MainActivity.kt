package shop.corgi.client.ui

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import shop.corgi.client.core.I18n
import shop.corgi.client.core.Ping
import shop.corgi.client.core.Scheme
import shop.corgi.client.data.Store
import shop.corgi.client.engine.Xray
import shop.corgi.client.vpn.UpdateJob
import shop.corgi.client.vpn.ClientVpnService
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {
    private companion object { const val HANDLED = "shop.corgi.client.handled" }

    /** Text waiting in «Добавить» (shared, scanned, a link or corgi://import) — confirmed by the user. */
    val incoming = androidx.compose.runtime.mutableStateOf<String?>(null)

    private val permission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (VpnService.prepare(this) == null) ClientVpnService.start(this)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = Store(this)
        I18n.apply(store.settings.lang)
        UpdateJob.schedule(this)
        if (savedInstanceState == null) thread {
            val s = store.settings
            runCatching { if (s.updateOnLaunch) store.updateAll() else store.updateDue() }
            if (s.pingOnLaunch) runCatching {
                store.pings = store.pings + Ping.all(store.profiles.flatMap { it.servers() }, s) { server -> Xray.measure(this, Ping.probeConfig(server), s.pingUrl) }
            }
            runCatching { store.checkUpdate() }
        }
        // Handled once: a recreation must not import or connect again. The intent is marked, not replaced — the system
        // and test tools (ActivityScenario) still recognise the activity by it.
        if (!intent.getBooleanExtra(HANDLED, false)) {
            incoming.value = handle(intent)
            ciHook(intent)
            intent.putExtra(HANDLED, true)
        }
        if (savedInstanceState == null && store.settings.autoConnectLaunch && store.active() != null
            && ClientVpnService.current(this) == ClientVpnService.STATE_OFF) connect()
        setContent { ClientApp(store, incoming, ::connect, pending) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        ciHook(intent)
        val text = handle(intent)
        setIntent(intent.putExtra(HANDLED, true))
        if (text != null) incoming.value = text
    }

    /** A corgi://routing/… or corgi://restore/… link waiting for the user's confirmation in the app. */
    val pending = androidx.compose.runtime.mutableStateOf<Scheme?>(null)

    /**
     * What an intent asks for: text to add (shown in «Добавить» to confirm), or a corgi:// action — connect, disconnect,
     * toggle and close run at once; rules and backups wait in ``pending`` for confirmation.
     */
    private fun handle(intent: Intent?): String? {
        val data = intent?.data?.toString()
        val scheme = data?.let { Scheme.parse(it) } ?: return importText(intent)
        when (scheme) {
            Scheme.Connect -> if (ClientVpnService.current(this) == ClientVpnService.STATE_OFF) connect()
            Scheme.Disconnect -> ClientVpnService.stop(this)
            Scheme.Toggle -> if (ClientVpnService.current(this) == ClientVpnService.STATE_OFF) connect() else ClientVpnService.stop(this)
            Scheme.Close -> { ClientVpnService.stop(this); finishAndRemoveTask() }
            Scheme.Open -> Unit
            is Scheme.Import -> return scheme.text
            is Scheme.Rules, is Scheme.Restore -> pending.value = scheme
        }
        return null
    }

    /** Asks for the VPN permission the first time, then starts the tunnel. */
    fun connect() {
        if (Store(this).settings.tunnelMode == "proxy") { ClientVpnService.start(this); return }
        val ask = VpnService.prepare(this)
        if (ask != null) permission.launch(ask) else ClientVpnService.start(this)
    }

    /** A link or text shared to the app, a vless:// … link opened from the browser, or corgiclient://import?url=… */
    private fun importText(intent: Intent?): String? = when (intent?.action) {
        Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)
        Intent.ACTION_VIEW -> intent.data?.let { uri -> if (uri.scheme == "corgiclient") uri.getQueryParameter("url") else if (uri.scheme == "corgi") null else uri.toString() }
        else -> null
    }

    /** CI only (debuggable builds, scripts/mobile/client-vpn-e2e.sh): import a subscription, connect, disconnect. */
    private fun ciHook(intent: Intent?) {
        if (intent == null || (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) == 0) return
        val store = Store(this)
        // Settings for the run (JSON merged over the current ones), e.g. {"tunnelMode":"proxy","proxyUser":"ci","proxyPass":"secret"}.
        intent.getStringExtra("client_test_settings")?.let { json ->
            runCatching {
                val merged = store.settings.toJson()
                val extra = org.json.JSONObject(json)
                extra.keys().forEach { merged.put(it, extra.get(it)) }
                store.settings = shop.corgi.client.core.Settings.of(merged)
            }
        }
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
