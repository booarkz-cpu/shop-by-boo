package shop.corgi.client.ui

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import shop.corgi.client.core.I18n
import shop.corgi.client.core.Ping
import shop.corgi.client.core.Scheme
import shop.corgi.client.data.Store
import shop.corgi.client.engine.Xray
import shop.corgi.client.vpn.UpdateJob
import shop.corgi.client.vpn.ClientVpnService
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {
    private companion object {
        const val HANDLED = "shop.corgi.client.handled"
        const val TILE_PREFERENCES = "android.service.quicksettings.action.QS_TILE_PREFERENCES"
    }

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
        // v1.9.0: the day counter is gone (master prompt v6); what earlier versions kept for it is deleted.
        deleteSharedPreferences("client_streak")
        shop.corgi.client.vpn.AppUpdateJob.schedule(this)
        // v1.6.1 (N11): «Обновление готово» → the checked APK goes to the system installer.
        if (intent?.action == shop.corgi.client.vpn.AppUpdateJob.ACTION_INSTALL) {
            val ready = store.readyUpdate()
            if (ready != null) runCatching { shop.corgi.client.vpn.ApkInstaller.install(this, ready) }
            // v1.9.6: «Доступна версия» on mobile data — the APK is downloaded now, then installed.
            else thread { runCatching { store.checkUpdate(force = true)?.let { u -> shop.corgi.client.vpn.ApkInstaller.install(this, store.downloadUpdate(u)) } } }
        }
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
        if (intent?.action == TILE_PREFERENCES) openTab.value = 1
        setContent {
            if (locked.value) LockScreen { unlock() } else ClientApp(store, incoming, ::connect, pending, openTab)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action == TILE_PREFERENCES) openTab.value = 1
        ciHook(intent)
        val text = handle(intent)
        setIntent(intent.putExtra(HANDLED, true))
        if (text != null) incoming.value = text
    }

    /** A corgi://routing/… or corgi://restore/… link waiting for the user's confirmation in the app. */
    val pending = androidx.compose.runtime.mutableStateOf<Scheme?>(null)

    /** v1.8.2 (N12): App Lock — the content stays hidden until the system prompt is passed. */
    val locked = androidx.compose.runtime.mutableStateOf(false)
    private var unlockedAt = 0L
    private var leftAt = 0L

    override fun onResume() {
        super.onResume()
        val enabled = Store(this).settings.appLock
        locked.value = shop.corgi.client.core.AppLock.locked(enabled, unlockedAt, leftAt, System.currentTimeMillis())
        // The prompt opens by itself once per return to the app; after «Отмена» it waits for the button (no prompt loop).
        if (locked.value && !autoPrompted) {
            autoPrompted = true
            unlock()
        }
    }

    private var autoPrompted = false

    override fun onStop() {
        super.onStop()
        autoPrompted = false
    }

    override fun onPause() {
        super.onPause()
        if (!locked.value) leftAt = System.currentTimeMillis()
    }

    /** The system prompt: fingerprint / face, or the phone's PIN, pattern or password; [then] after a success. */
    fun authenticate(then: () -> Unit) {
        val title = shop.corgi.client.core.tr("Корги Люси", "Corgi Lusi", "Коргі Люсі")
        val keyguard = getSystemService(android.app.KeyguardManager::class.java)
        if (keyguard?.isDeviceSecure != true) {
            android.widget.Toast.makeText(this, shop.corgi.client.core.tr("Сначала задайте блокировку экрана в настройках телефона",
                "Set a screen lock in the phone's settings first", "Спочатку задайте блокування екрана"), android.widget.Toast.LENGTH_LONG).show()
            return
        }
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            val prompt = android.hardware.biometrics.BiometricPrompt.Builder(this).setTitle(title)
                .setAllowedAuthenticators(android.hardware.biometrics.BiometricManager.Authenticators.BIOMETRIC_WEAK or
                    android.hardware.biometrics.BiometricManager.Authenticators.DEVICE_CREDENTIAL).build()
            prompt.authenticate(android.os.CancellationSignal(), mainExecutor, object : android.hardware.biometrics.BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: android.hardware.biometrics.BiometricPrompt.AuthenticationResult?) { then() }
            })
        } else {
            @Suppress("DEPRECATION")
            val intent = keyguard!!.createConfirmDeviceCredentialIntent(title, null) ?: run { then(); return }
            pendingUnlock = then
            confirm.launch(intent)
        }
    }

    private var pendingUnlock: (() -> Unit)? = null
    private val confirm = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == RESULT_OK) pendingUnlock?.invoke()
        pendingUnlock = null
    }

    private fun unlock() = authenticate {
        unlockedAt = System.currentTimeMillis()
        leftAt = 0L
        locked.value = false
    }

    /** v1.8.0 (N12): the tab to show — 1 (servers) after a long press on the quick settings tile. */
    val openTab = androidx.compose.runtime.mutableStateOf<Int?>(null)

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

/** v1.8.2 (N12): what shows while the app is locked — the mascot asleep and one button. */
@androidx.compose.runtime.Composable
private fun LockScreen(unlock: () -> Unit) {
    androidx.compose.foundation.layout.Column(
        androidx.compose.ui.Modifier.fillMaxSize().background(androidx.compose.material3.MaterialTheme.colorScheme.background).padding(24.dp),
        verticalArrangement = androidx.compose.foundation.layout.Arrangement.Center,
        horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally
    ) {
        androidx.compose.foundation.Image(androidx.compose.ui.res.painterResource(shop.corgi.client.R.drawable.mascot_sleep), null,
            androidx.compose.ui.Modifier.size(160.dp))
        androidx.compose.material3.Text(shop.corgi.client.core.tr("Приложение заблокировано", "The app is locked", "Застосунок заблоковано"),
            style = androidx.compose.material3.MaterialTheme.typography.titleMedium)
        androidx.compose.material3.Button(onClick = unlock, modifier = androidx.compose.ui.Modifier.padding(top = 16.dp).testTag("unlock")) {
            androidx.compose.material3.Text(shop.corgi.client.core.tr("Разблокировать", "Unlock", "Розблокувати"))
        }
    }
}
