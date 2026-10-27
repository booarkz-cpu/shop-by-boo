package shop.remnawave.user

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.fragment.app.FragmentActivity
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.AlertDialog
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.DisposableEffect
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.compose.runtime.Composable
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material3.Checkbox
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.UUID
import java.util.Locale
import java.util.concurrent.Executors
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.concurrent.thread
import shop.remnawave.user.passkey.CorgiPasskeys
import shop.remnawave.user.push.CorgiPush
import shop.remnawave.user.widget.CorgiWidgetData
import shop.remnawave.user.analytics.CorgiAnalytics
import shop.remnawave.user.security.CorgiTrust
import shop.remnawave.user.ui.*
import shop.remnawave.user.vpn.CorgiVpnService
import shop.remnawave.user.vpn.VpnClients
import shop.remnawave.user.vpn.XrayEngine



/** Tokens are encrypted by a non-exportable Android Keystore AES-GCM key.
 * The API origin is authenticated as AAD. Legacy plaintext sessions are discarded.
 */
class SecureTokenStore(private val prefs: android.content.SharedPreferences) {
    private val alias = "shop.session.v2"
    init { prefs.edit().remove("token").commit() }
    private fun key(): javax.crypto.SecretKey {
        val store = java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? javax.crypto.SecretKey)?.let { return it }
        val generator = javax.crypto.KeyGenerator.getInstance("AES", "AndroidKeyStore")
        generator.init(android.security.keystore.KeyGenParameterSpec.Builder(alias,
            android.security.keystore.KeyProperties.PURPOSE_ENCRYPT or android.security.keystore.KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes("GCM").setEncryptionPaddings("NoPadding").setKeySize(256).build())
        return generator.generateKey()
    }
    fun clear() { prefs.edit().remove("token").remove("secure_token").commit() }
    fun read(): String {
        val encoded = prefs.getString("secure_token", null) ?: return ""
        return try {
            val raw = android.util.Base64.decode(encoded, android.util.Base64.NO_WRAP)
            require(raw.size > 28)
            val cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(javax.crypto.Cipher.DECRYPT_MODE, key(), javax.crypto.spec.GCMParameterSpec(128, raw.copyOfRange(0, 12)))
            cipher.updateAAD((prefs.getString("base", "") ?: "").toByteArray(Charsets.UTF_8))
            String(cipher.doFinal(raw.copyOfRange(12, raw.size)), Charsets.UTF_8)
        } catch (_: Exception) { clear(); "" }
    }
    fun write(token: String, base: String) {
        if (token.isBlank()) { clear(); return }
        val cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(javax.crypto.Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(base.toByteArray(Charsets.UTF_8))
        val encoded = android.util.Base64.encodeToString(cipher.iv + cipher.doFinal(token.toByteArray(Charsets.UTF_8)), android.util.Base64.NO_WRAP)
        check(prefs.edit().putString("base", base).putString("secure_token", encoded).remove("token").commit()) {
            "Could not securely store the session"
        }
    }
}

class MainActivity : FragmentActivity() {
    companion object {
        /** corgi://login?base=…&code=… waiting to be redeemed (cold start or onNewIntent). */
        val pendingLogin = androidx.compose.runtime.mutableStateOf<LoginLink?>(null)
        /** Section a tapped push (or its button) opens. */
        val pendingTab = androidx.compose.runtime.mutableStateOf<String?>(null)
        /** corgi://payment?order=… — back from the payment page: show how the order went. */
        val pendingPayment = androidx.compose.runtime.mutableStateOf<String?>(null)
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        LoginLink.parse(intent.data)?.let { pendingLogin.value = it }
        paymentOrder(intent.data)?.let { pendingPayment.value = it }
        intent.getStringExtra(CorgiPush.EXTRA_TAB)?.let { pendingTab.value = it }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CorgiTrust.appContext = applicationContext
        LoginLink.parse(intent?.data)?.let { pendingLogin.value = it }
        paymentOrder(intent?.data)?.let { pendingPayment.value = it }
        // Screenshot mode for CI: debuggable builds only, started with --ez corgi_demo true.
        val demo = (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0 && flag(intent, "corgi_demo")
        if (!demo) window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        // A tapped push opens the notification center (FCM puts the data payload into extras).
        val initialTab = if (demo) intent?.getStringExtra("corgi_tab") ?: "overview"
            else if (intent?.hasExtra(CorgiPush.EXTRA_TAB) == true) intent?.getStringExtra(CorgiPush.EXTRA_TAB)?.takeIf { Regex("[a-z][a-z0-9_-]{0,31}").matches(it) } ?: "notifications"
            else if (intent?.hasExtra("notification_id") == true) "notifications" else "overview"
        val demoLang = if (demo) intent?.getStringExtra("corgi_lang") else null
        setContent { MaterialTheme(colorScheme = shopColors()) { UserApp(initialTab, demo, demoLang) } }
    }
}

private fun shopColors() = darkColorScheme(
    primary = Color(0xFF8A79FF),
    onPrimary = Color(0xFF18122D),
    background = Color(0xFF0C1021),
    onBackground = Color(0xFFF4F7FB),
    surface = Color(0xFF151A31),
    onSurface = Color(0xFFF4F7FB),
)

private val localHttpHosts = setOf("localhost", "127.0.0.1", "10.0.2.2")

private val ORDER_ID = Regex("[A-Za-z0-9_.:-]{6,128}")

/** Order of corgi://payment?order=… (backend/app/app_login.py payment_link); null for anything else. */
fun paymentOrder(uri: Uri?): String? {
    if (uri == null || uri.scheme != "corgi" || uri.host != "payment") return null
    return uri.getQueryParameter("order")?.takeIf { ORDER_ID.matches(it) }
}

/** Sign-in link: the shop it belongs to and a one-use code (backend/app/app_login.py). */
data class LoginLink(val base: String, val code: String) {
    companion object {
        private val CODE = Regex("[A-Za-z0-9_-]{20,128}")
        fun parse(uri: Uri?): LoginLink? {
            if (uri == null || uri.scheme != "corgi" || uri.host != "login") return null
            val code = uri.getQueryParameter("code").orEmpty()
            if (!CODE.matches(code)) return null
            val base = try { normalizeBase(uri.getQueryParameter("base").orEmpty()) } catch (_: Exception) { "" }
            return LoginLink(base, code)
        }
        /** The shop the link may sign in to: a baked address wins, a foreign one is refused. */
        fun target(link: LoginLink, baked: String, current: String): String? {
            if (baked.isNotBlank()) return if (link.base.isBlank() || link.base == baked) baked else null
            if (link.base.isNotBlank()) return link.base
            return current.ifBlank { null }
        }
    }
}

fun pkceVerifier(): String {
    val bytes = ByteArray(32)
    java.security.SecureRandom().nextBytes(bytes)
    return android.util.Base64.encodeToString(bytes, android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING)
}
fun pkceChallenge(verifier: String): String = android.util.Base64.encodeToString(
    java.security.MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(Charsets.US_ASCII)),
    android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING)


fun subscriptionApps(url: String): List<Pair<String, String>> {
    if (!url.startsWith("https://") || url.any { it.isWhitespace() }) return emptyList()
    val encoded = Uri.encode(url)
    return listOf("Happ" to "happ://add/$encoded", "v2rayNG" to "v2rayng://install-sub?url=$encoded", "Streisand" to "streisand://import/$encoded")
}

fun promptUnlock(activity: FragmentActivity, title: String, onResult: (Boolean) -> Unit) {
    val authenticators = BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL
    try {
        if (BiometricManager.from(activity).canAuthenticate(authenticators) != BiometricManager.BIOMETRIC_SUCCESS) {
            onResult(false)
            return
        }
        val prompt = BiometricPrompt(activity, androidx.core.content.ContextCompat.getMainExecutor(activity), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) { activity.runOnUiThread { onResult(activity.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) } }
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) { activity.runOnUiThread { onResult(false) } }
        })
        prompt.authenticate(BiometricPrompt.PromptInfo.Builder().setTitle(title).setAllowedAuthenticators(authenticators).build())
    } catch (_: Exception) {
        onResult(false)
    }
}

fun externalUrlAllowed(raw: String): Boolean {
    if (raw.isBlank() || raw.any { it.isWhitespace() }) return false
    val uri = try { URI(raw) } catch (_: Exception) { return false }
    val host = uri.host?.lowercase() ?: return false
    if (uri.userInfo != null) return false
    if (uri.scheme == "https") return true
    return uri.scheme == "http" && host in localHttpHosts
}

fun normalizeBase(raw: String): String {
    val value = raw.trim().trimEnd('/')
    val uri = try { URI(value) } catch (_: Exception) { throw IllegalArgumentException("https") }
    val host = uri.host?.lowercase() ?: throw IllegalArgumentException("https")
    if (uri.userInfo != null || value.any { it.isWhitespace() }) throw IllegalArgumentException("https")
    if (uri.scheme == "https") return value
    if (uri.scheme == "http" && host in localHttpHosts) return value
    throw IllegalArgumentException("https")
}

fun safeMediaPath(path: String): String? {
    if (!path.startsWith("/media/") || ".." in path || "\\" in path || "://" in path || "?" in path || "#" in path) return null
    val name = path.removePrefix("/media/")
    if (name.isBlank() || "/" in name) return null
    return path
}

fun loadLogoBitmap(base: String, path: String): android.graphics.Bitmap? {
    val safe = safeMediaPath(path) ?: return null
    val connection = (URL(base + safe).openConnection() as HttpURLConnection).apply {
        instanceFollowRedirects = false
        connectTimeout = 15000
        readTimeout = 15000
        setRequestProperty("Accept", "image/png,image/jpeg,image/webp")
    }
    if (connection.responseCode !in 200..299) return null
    val bytes = connection.inputStream.use { it.readBytes() }
    if (bytes.size > 2 * 1024 * 1024) return null
    return android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
}

fun publicNode(row: JSONObject): JSONObject {
    val status = row.optString("status", "unknown")
    val safeStatus = if (status in setOf("online", "offline", "disabled", "unknown")) status else "unknown"
    var name = row.optString("name", "node").ifBlank { "node" }
    if ("://" in name || name.count { it == '.' } >= 3 && name.any { it.isDigit() }) name = "node"
    return JSONObject().put("name", name).put("country", row.optString("country")).put("status", safeStatus).put("users_online", row.optInt("users_online", 0))
}

class ShopApi(private val base: String, private val token: String, private val lang: String) {
    fun get(path: String): Any = call("GET", path, null, null, emptyMap())
    fun post(path: String, body: JSONObject, idempotency: String? = null, headers: Map<String, String> = emptyMap()): Any =
        call("POST", path, body, idempotency, headers)
    fun delete(path: String): Any = call("DELETE", path, null, null, emptyMap())

    private fun call(method: String, path: String, body: JSONObject?, idempotency: String?, headers: Map<String, String>): Any {
        // Every sign-in that issues a session (password or passkey) is bound to a fresh PKCE verifier.
        val verifier = if (path in setOf("/api/auth/login", "/api/auth/register", "/api/admin/auth/login", "/api/auth/passkeys/login/verify", "/api/auth/mobile/code")) pkceVerifier() else null
        val connection = (URL(base + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            instanceFollowRedirects = false
            connectTimeout = 15000
            readTimeout = 15000
            setRequestProperty("Accept", "application/json")
            if (verifier != null) setRequestProperty("X-Shop-Code-Challenge", pkceChallenge(verifier))
            setRequestProperty("Accept-Language", lang)
            setRequestProperty("User-Agent", "CorgiLusi-Android-User/3.1.0")
            // Historical compatibility marker: CorgiLusi-Android-User/2.9.0
            setRequestProperty("X-Shop-Client", "android-user")


            if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token")
            if (idempotency != null) setRequestProperty("Idempotency-Key", idempotency)
            headers.forEach { (name, value) -> setRequestProperty(name, value) }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }
        }
        // The pinned shop must present a pinned key before the body or the session leaves the phone.
        connection.connect()
        CorgiTrust.verify(connection)
        if (body != null) connection.outputStream.use { it.write(body.toString().toByteArray()) }
        val code = connection.responseCode
        val text = (if (code in 200..299) connection.inputStream else connection.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code !in 200..299) throw IllegalStateException(detailOf(text, code))
        val trimmed = text.trim()
        val result: Any = if (trimmed.startsWith("[")) JSONArray(trimmed) else JSONObject(if (trimmed.isBlank()) "{}" else trimmed)
        if (verifier != null && result is JSONObject && result.has("authorization_code")) {
            val proof = CorgiTrust.integrityHeaders(base) { get(it) as JSONObject }
            val exchanged = post("/api/auth/mobile/token", JSONObject().put("code", result.getString("authorization_code")).put("code_verifier", verifier), headers = proof) as JSONObject
            result.remove("authorization_code")
            result.put("access_token", exchanged.getString("access_token"))
            result.put("token_type", "bearer")
        }
        return result
    }
}

private fun detailOf(payload: String, status: Int): String {
    return try {
        val detail = JSONObject(payload).opt("detail")
        when (detail) {
            is String -> if (detail.isBlank()) "HTTP $status" else detail.take(300)
            is JSONArray -> detail.optJSONObject(0)?.optString("msg")?.take(300) ?: "HTTP $status"
            else -> "HTTP $status"
        }
    } catch (_: Exception) {
        "HTTP $status"
    }
}

@Composable
private fun UserApp(initialTab: String = "overview", demo: Boolean = false, demoLang: String? = null) {
    val context = LocalContext.current
    val activity = context as FragmentActivity
    val prefs = remember { context.getSharedPreferences("shop_user", 0) }
    val tokenStore = remember { SecureTokenStore(prefs) }
    var lang by remember { mutableStateOf(demoLang ?: prefs.getString("lang", null) ?: autoLanguage()) }
    // A shop address baked into the build (corgi.shop_url) replaces the address field.
    val bakedBase = BuildConfig.SHOP_URL
    var base by remember { mutableStateOf(bakedBase.ifBlank { prefs.getString("base", "") ?: "" }) }
    // Sign-in methods the shop has configured (GET /api/public/app-login/methods).
    var methods by remember { mutableStateOf(JSONObject()) }
    var token by remember { mutableStateOf(if (demo) "demo" else tokenStore.read()) }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var unlocked by remember { mutableStateOf(demo || token.isBlank()) }
    var layout by remember { mutableStateOf(LayoutStore.cached(context, base, lang) ?: LayoutStore.bundled(context, lang)) }
    var data by remember { mutableStateOf(ShopData()) }
    var ui by remember {
        mutableStateOf(UiFlags(pushEnabled = CorgiPush.enabled(context), widgetEnabled = CorgiWidgetData.enabled(context), engine = CorgiVpnService.useEngine(context),
            version = "Corgi Lusi ${BuildConfig.VERSION_NAME}"))
    }
    // The layout decides which sections exist; a push opens notifications, otherwise the VPN screen.
    var tab by remember { mutableStateOf(if (initialTab == "overview") "vpn" else initialTab) }
    var dialog by remember { mutableStateOf("") }
    // A document opened from «Информация» or a «Открыть документ» button (GET /api/public/info-pages/{kind}).
    var openDoc by remember { mutableStateOf<JSONObject?>(null) }
    // Shop logo from «Android и iOS → логотип» (GET /api/public/apps), shown on sign-in and in the header.
    var logo by remember { mutableStateOf<ImageBitmap?>(null) }
    fun loadLogo(origin: String) {
        if (demo || origin.isBlank()) return
        thread {
            try {
                val catalog = ShopApi(origin, "", lang).get("/api/public/apps") as JSONObject
                val image = loadLogoBitmap(origin, catalog.optString("logo_url"))?.asImageBitmap()
                activity.runOnUiThread { logo = image }
            } catch (_: Exception) { }
        }
    }
    var dialogText by remember { mutableStateOf("") }
    var dialogText2 by remember { mutableStateOf("") }
    val strings = remember(lang) { loadStrings(context, lang) }
    // A string replaced in the admin panel («Строки приложения») wins over the bundled one.
    fun t(key: String) = layout.strings[key] ?: strings.optString(key, key)
    fun notice(text: String) { ui = ui.copy(notice = text) }
    fun track(event: String, screen: String = "") {
        if (!demo) CorgiAnalytics.track(context, base, token, event, screen)
    }

    DisposableEffect(activity) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) unlocked = demo }
        activity.lifecycle.addObserver(observer)
        // The VPN state of the phone: any VPN network (Happ, v2rayNG, Hiddify…) counts as «connected».
        val stop = if (demo) ({}) else VpnClients.watch(context) { on ->
            activity.runOnUiThread { ui = ui.copy(vpn = if (on) VpnState.ON else if (ui.vpn == VpnState.CONNECTING) VpnState.CONNECTING else VpnState.OFF) }
        }
        // State of the embedded engine: connected, connecting or stopped (with the reason, if any).
        val engineListener: (String) -> Unit = { state ->
            activity.runOnUiThread {
                val error = vpnPrefs(context).getString(CorgiVpnService.KEY_ERROR, "").orEmpty()
                ui = when (state) {
                    CorgiVpnService.STATE_ON -> ui.copy(vpn = VpnState.ON)
                    CorgiVpnService.STATE_CONNECTING -> ui.copy(vpn = VpnState.CONNECTING)
                    else -> ui.copy(vpn = VpnState.OFF, notice = if (error.isNotBlank()) t("vpn_engine_error").replace("{error}", error) else ui.notice)
                }
            }
        }
        if (!demo) CorgiVpnService.listeners.add(engineListener)
        onDispose { activity.lifecycle.removeObserver(observer); stop(); CorgiVpnService.listeners.remove(engineListener) }
    }

    fun saveSession(nextBase: String, nextToken: String) {
        base = nextBase
        token = nextToken
        if (!demo) CorgiAnalytics.track(context, nextBase, nextToken, "sign_in")
        password = ""
        unlocked = activity.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
        prefs.edit().putString("lang", lang).apply()
    }
    fun signOut() {
        val previous = token
        val origin = base
        tokenStore.clear()
        token = ""
        unlocked = false
        data = ShopData()
        ui = ui.copy(pushEnabled = false, widgetEnabled = false)
        CorgiWidgetData.clear(context)
        thread {
            // Revoke the push token while the session is still valid, then end the session.
            CorgiPush.unregister(context, origin, previous, lang)
            try {
                if (previous.isNotBlank()) ShopApi(origin, previous, lang).post("/api/auth/logout", JSONObject())
            } catch (_: Exception) {
                activity.runOnUiThread { notice("Signed out locally; server session revocation could not be confirmed.") }
            }
        }
    }
    fun work(block: () -> Unit) {
        ui = ui.copy(busy = true, notice = "")
        thread {
            val error = try { block(); null } catch (exc: Exception) { exc.message ?: "HTTP" }
            activity.runOnUiThread { ui = ui.copy(busy = false, notice = error ?: ui.notice) }
        }
    }
    fun loadMethods(origin: String) {
        if (demo || origin.isBlank()) return
        thread {
            try {
                val next = ShopApi(origin, "", lang).get("/api/public/app-login/methods") as JSONObject
                activity.runOnUiThread { methods = next }
            } catch (_: Exception) { }
        }
    }
    fun redeemLink(link: LoginLink) {
        val origin = LoginLink.target(link, bakedBase, base) ?: run { notice(t("login_link_foreign")); return }
        work {
            val response = ShopApi(origin, "", lang).post("/api/auth/mobile/code", JSONObject().put("code", link.code)) as JSONObject
            val issued = response.optString("access_token")
            if (issued.isBlank()) throw IllegalStateException(t("login_link_invalid"))
            tokenStore.write(issued, origin)
            activity.runOnUiThread { prefs.edit().putString("base", origin).apply(); saveSession(origin, issued) }
        }
    }
    fun loadLayout(origin: String) {
        if (demo || origin.isBlank()) return
        thread { LayoutStore.fetch(context, origin, lang)?.let { next -> activity.runOnUiThread { layout = next } } }
    }
    fun enablePush() {
        work {
            if (!CorgiPush.buildSupportsPush()) throw IllegalStateException(t("push_unavailable"))
            val response = CorgiPush.register(context, base, token, lang)
            activity.runOnUiThread { ui = ui.copy(pushEnabled = true, notice = if (response.optBoolean("push_available")) t("push_on") else t("push_server_off")) }
        }
    }
    val notificationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) enablePush() else notice(t("push_denied"))
    }
    // The embedded VPN asks the system once for the VPN permission (VpnService.prepare).
    val vpnPermission = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == android.app.Activity.RESULT_OK && data.subscriptionUrl.isNotBlank()) {
            ui = ui.copy(vpn = VpnState.CONNECTING); CorgiVpnService.start(context, data.subscriptionUrl)
        } else notice(t("vpn_permission_denied"))
    }
    fun engineConnect() {
        if (data.subscriptionUrl.isBlank()) {
            notice(t("need_subscription"))
            layout.sections.firstOrNull { it.kind == "premium" }?.let { tab = it.id }
            return
        }
        if (CorgiVpnService.current(context) != CorgiVpnService.STATE_OFF || ui.vpn == VpnState.ON) {
            CorgiVpnService.stop(context); ui = ui.copy(vpn = VpnState.OFF); return
        }
        val ask = android.net.VpnService.prepare(context)
        if (ask != null) vpnPermission.launch(ask)
        else { ui = ui.copy(vpn = VpnState.CONNECTING); CorgiVpnService.start(context, data.subscriptionUrl) }
    }
    fun restartEngine() {
        if (CorgiVpnService.current(context) == CorgiVpnService.STATE_ON && data.subscriptionUrl.isNotBlank()) {
            CorgiVpnService.stop(context)
            thread { Thread.sleep(800); activity.runOnUiThread { CorgiVpnService.start(context, data.subscriptionUrl) } }
        }
    }
    fun refresh() {
        val api = ShopApi(base, token, lang)
        loadLayout(base)
        loadLogo(base)
        thread {
            // Re-bind the push token to the current session (tokens rotate, sessions are re-issued).
            if (CorgiPush.enabled(context) && CorgiPush.permissionGranted(context)) {
                try { CorgiPush.register(context, base, token, lang) } catch (_: Exception) { }
            }
            if (CorgiWidgetData.enabled(context)) CorgiWidgetData.refresh(context)
            try {
                val servers = api.get("/api/me/servers") as JSONObject
                // Node names that look like addresses are never shown (publicNode).
                val nodes = servers.optJSONArray("nodes") ?: JSONArray()
                val safe = JSONArray()
                for (i in 0 until nodes.length()) nodes.optJSONObject(i)?.let { safe.put(publicNode(it)) }
                servers.put("nodes", safe)
                val next = ShopData(
                    dashboard = api.get("/api/me/dashboard") as JSONObject,
                    profiles = api.get("/api/me/subscriptions") as JSONArray,
                    plans = api.get("/api/plans") as JSONArray,
                    servers = servers,
                    connection = api.get("/api/me/connection-info") as JSONObject,
                    traffic = api.get("/api/me/traffic") as JSONObject,
                    devices = api.get("/api/me/devices") as JSONArray,
                    notifications = api.get("/api/me/mobile/notifications?unread_only=false") as JSONArray,
                    routing = api.get("/api/me/routing/recommendation") as JSONObject,
                    config = api.get("/api/public/config") as JSONObject,
                    qr = loadAuthedPng(base, "/api/me/connection-qr", token, lang),
                    // Shops on releases before v28.25.0 have no family or status page: keep the rest working.
                    family = try { api.get("/api/me/family") as JSONObject } catch (_: Exception) { JSONObject() },
                    status = try { api.get("/api/public/service-status") as JSONObject } catch (_: Exception) { JSONObject() },
                    passkeys = try { CorgiPasskeys.list(base, token, lang) } catch (_: Exception) { JSONArray() },
                    // Shops before v28.29.0 have no documents: the section stays empty.
                    docs = try { api.get("/api/public/info-pages?lang=$lang") as JSONArray } catch (_: Exception) { JSONArray() },
                    giveaways = try { (api.get("/api/me/giveaways") as JSONObject).optJSONArray("items") ?: JSONArray() } catch (_: Exception) { JSONArray() },
                )
                activity.runOnUiThread { data = next; ui = ui.copy(offline = false) }
            } catch (exc: Exception) {
                activity.runOnUiThread { ui = ui.copy(offline = true, notice = exc.message ?: "") }
            }
        }
    }
    fun openExternal(url: String) {
        if (!(externalUrlAllowed(url) || url.startsWith("tg://"))) { notice(t("link_missing")); return }
        try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } catch (_: ActivityNotFoundException) { notice(url) }
    }
    fun openOAuth(provider: String) {
        val origin = try { normalizeBase(base) } catch (_: Exception) { notice(t("https_required")); return }
        // The browser comes back with corgi://login?code=… (app=1 in the OAuth state).
        openExternal("$origin/api/auth/$provider?app=1")
    }
    fun copy(label: String, value: String) {
        if (value.isBlank()) return
        context.getSystemService(android.content.ClipboardManager::class.java)?.setPrimaryClip(android.content.ClipData.newPlainText(label, value))
        notice(t("copied"))
    }
    fun referralLink(): String {
        val code = data.user.optString("referral_code")
        val bot = data.config.optString("bot_username")
        return if (bot.isNotBlank() && code.isNotBlank()) "https://t.me/$bot?start=ref_$code" else code
    }
    fun share(text: String) {
        if (text.isBlank()) return
        context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), null))
    }
    fun pay(planId: Int) {
        track("checkout_start")
        work {
            val body = JSONObject().put("provider", providerOf(data.config))
            if (planId > 0) body.put("plan_id", planId) else {
                // A shop that sells only through the tariff constructor: its first enabled options.
                val builders = ShopApi(base, token, lang).get("/api/tariff-constructors") as JSONArray
                val row = builders.optJSONObject(0) ?: throw IllegalStateException(t("nodes_empty"))
                val picked = pickOptions(row.optJSONArray("options") ?: JSONArray())
                body.put("constructor_id", row.getInt("id")).put("device_option_id", picked.optInt("devices"))
                    .put("traffic_option_id", picked.optInt("traffic_gb")).put("days_option_id", picked.optInt("days"))
            }
            data.subscription?.optInt("id")?.takeIf { it > 0 }?.let { body.put("subscription_id", it) }
            val response = ShopApi(base, token, lang).post("/api/payments/create", body, UUID.randomUUID().toString()) as JSONObject
            val url = response.optString("url")
            activity.runOnUiThread {
                notice(t("payment_created"))
                if (externalUrlAllowed(url)) context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }
        }
    }
    fun selectedPlanId(): Int = ui.selectedPlan.takeIf { it > 0 } ?: data.plans.optJSONObject(0)?.optInt("id") ?: 0

    val actions = object : ShopActions {
        override fun open(sectionId: String) { if (layout.section(sectionId) != null) { tab = sectionId; openDoc = null; ui = ui.copy(notice = "") } }
        override fun link(url: String) = openExternal(url)
        override fun selectPlan(planId: Int) { ui = ui.copy(selectedPlan = planId); track("plan_select") }
        override fun setTopupAmount(amount: String) { ui = ui.copy(topupAmount = amount) }
        override fun selectSubscription(subscriptionId: Int) = work {
            ShopApi(base, token, lang).post("/api/me/subscriptions/$subscriptionId/select", JSONObject())
            activity.runOnUiThread { refresh() }
        }
        override fun revokeDevice(deviceId: Int) = work {
            ShopApi(base, token, lang).post("/api/me/devices/$deviceId/revoke", JSONObject())
            activity.runOnUiThread { notice(t("device_revoked")); refresh() }
        }
        override fun markRead(notificationId: Int) = work {
            ShopApi(base, token, lang).post("/api/me/mobile/notifications/$notificationId/read", JSONObject())
            activity.runOnUiThread { refresh() }
        }
        override fun removeFamilyMember(memberId: Int) = work {
            ShopApi(base, token, lang).delete("/api/me/family/members/$memberId")
            activity.runOnUiThread { refresh() }
        }
        override fun joinFamily(code: String) = work {
            ShopApi(base, token, lang).post("/api/me/family/join", JSONObject().put("code", code))
            activity.runOnUiThread { notice(t("family_joined")); refresh() }
        }
        override fun enterGiveaway(giveawayId: Int) = work {
            track("giveaway_enter")
            val row = ShopApi(base, token, lang).post("/api/me/giveaways/$giveawayId/enter", JSONObject()) as JSONObject
            val mine = row.optJSONObject("my_entry")
            activity.runOnUiThread {
                notice(if (mine?.optString("outcome") == "won") layout.text("giveaway_won").replace("{amount}", "${mine.optString("reward_amount")} ${row.optString("currency")}")
                    else layout.text("giveaway_entered"))
                refresh()
            }
        }
        override fun deletePasskey(passkeyId: Int) { dialog = "passkey_delete:$passkeyId"; dialogText = "" }
        override fun openDocument(kind: String) {
            if (kind !in setOf("faq", "rules", "privacy", "offer")) return
            if (demo) {
                openDoc = JSONObject().put("kind", kind).put("title", layout.sections.flatMap { it.buttons }.firstOrNull { it.action == "document" && it.target == kind }?.label ?: kind)
                    .put("body", "## Корги Люси\n- Один аккаунт — до пяти устройств\n- Возврат в течение **30 дней**\n\nВопросы — в поддержку.")
                    .put("banner", "/api/bot/banners/default/app-info.jpg")
                return
            }
            work {
                val page = ShopApi(base, token, lang).get("/api/public/info-pages/$kind?lang=$lang") as JSONObject
                activity.runOnUiThread { openDoc = page }
            }
        }
        override fun run(button: LayoutButton) {
            when (button.action) {
                "connect", "auto_location" -> {
                    track("connect_tap")
                    if (demo) { ui = ui.copy(vpn = if (ui.vpn == VpnState.ON) VpnState.OFF else VpnState.ON); return }
                    if (CorgiVpnService.useEngine(context)) {
                        if (button.action == "auto_location") { vpnPrefs(context).edit().remove(CorgiVpnService.KEY_SERVER).apply(); restartEngine(); notice(t("vpn_server_auto")) }
                        else engineConnect()
                        return
                    }
                    when (VpnClients.connect(context, data.subscriptionUrl)) {
                        VpnClients.Result.Imported -> {
                            ui = ui.copy(vpn = VpnState.CONNECTING, notice = t("vpn_imported"))
                            // The tunnel is switched on in the client; without it the status returns to «off» in a minute.
                            thread {
                                Thread.sleep(60_000)
                                activity.runOnUiThread { if (ui.vpn == VpnState.CONNECTING) ui = ui.copy(vpn = VpnState.OFF) }
                            }
                        }
                        VpnClients.Result.Opened -> notice(t("vpn_opened"))
                        VpnClients.Result.NoClient -> dialog = "install"
                        VpnClients.Result.NoSubscription -> {
                            notice(t("need_subscription"))
                            layout.sections.firstOrNull { it.kind == "premium" }?.let { tab = it.id }
                        }
                    }
                }
                "open" -> open(button.target)
                "url" -> openExternal(button.target)
                "document" -> openDocument(button.target)
                "cabinet" -> openExternal(layout.links["cabinet"].orEmpty())
                "telegram_channel" -> openExternal(layout.links["telegram_channel"].orEmpty())
                "import_app" -> {
                    if (data.subscriptionUrl.isBlank()) notice(t("need_subscription"))
                    else if (!VpnClients.importInto(context, button.target, data.subscriptionUrl)) dialog = "install"
                }
                "copy_subscription" -> copy("subscription", data.subscriptionUrl)
                "show_qr" -> dialog = "qr"
                "copy_id" -> copy("id", data.customerId)
                "buy" -> pay(selectedPlanId())
                "pay_wallet" -> work {
                    val body = JSONObject().put("plan_id", selectedPlanId())
                    data.subscription?.optInt("id")?.takeIf { it > 0 }?.let { body.put("subscription_id", it) }
                    ShopApi(base, token, lang).post("/api/me/wallet/spend", body, UUID.randomUUID().toString())
                    activity.runOnUiThread { notice(t("paid_wallet")); refresh() }
                }
                "trial" -> work {
                    track("trial_tap")
                    val planId = selectedPlanId()
                    if (planId == 0) throw IllegalStateException(t("nodes_empty"))
                    ShopApi(base, token, lang).post("/api/me/trial", JSONObject().put("plan_id", planId).put("days", data.config.optInt("trial_days", 3)))
                    activity.runOnUiThread { notice(t("trial_started")); refresh() }
                }
                "topup" -> {
                    val amount = ui.topupAmount.trim()
                    work {
                        val body = JSONObject().put("amount", amount).put("provider", providerOf(data.config))
                        val response = ShopApi(base, token, lang).post("/api/me/wallet/topup", body, UUID.randomUUID().toString()) as JSONObject
                        val url = response.optString("url")
                        activity.runOnUiThread {
                            notice(t("topup_ok"))
                            if (externalUrlAllowed(url)) context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        }
                    }
                }
                "redeem" -> { dialog = "redeem"; dialogText = "" }
                "share_referral" -> share(referralLink())
                "copy_referral" -> copy("referral", referralLink())
                "family_invite" -> work {
                    val owned = data.family.optJSONArray("owned")?.optJSONObject(0) ?: throw IllegalStateException(t("family_none"))
                    val existing = owned.optJSONObject("invite")?.optString("bot").orEmpty()
                    val link = existing.ifBlank {
                        val created = ShopApi(base, token, lang).post("/api/me/family/${owned.optInt("subscription_id")}/invite", JSONObject()) as JSONObject
                        created.optString("bot").ifBlank { created.optString("code") }
                    }
                    activity.runOnUiThread { share(link); refresh() }
                }
                "support_ticket" -> { dialog = "ticket"; dialogText = ""; dialogText2 = "" }
                "report_problem" -> { dialog = "report"; dialogText = "" }
                "language" -> {
                    lang = nextLanguage(lang)
                    prefs.edit().putString("lang", lang).apply()
                    layout = LayoutStore.cached(context, base, lang) ?: LayoutStore.bundled(context, lang)
                    loadLayout(base)
                }
                "push_toggle" -> if (ui.pushEnabled) {
                    val session = token
                    work {
                        CorgiPush.unregister(context, base, session, lang)
                        activity.runOnUiThread { ui = ui.copy(pushEnabled = false, notice = t("push_off")) }
                    }
                } else if (android.os.Build.VERSION.SDK_INT >= 33 && !CorgiPush.permissionGranted(context)) {
                    notificationPermission.launch(android.Manifest.permission.POST_NOTIFICATIONS)
                } else enablePush()
                "widget_toggle" -> {
                    val next = !ui.widgetEnabled
                    CorgiWidgetData.setEnabled(context, next)
                    ui = ui.copy(widgetEnabled = next)
                    if (next) work { CorgiWidgetData.refresh(context) }
                }
                "passkey_add" -> { dialog = "passkey_add"; dialogText = "" }
                "vpn_mode" -> {
                    if (!XrayEngine.available()) { notice(t("vpn_engine_missing")); return }
                    val next = if (CorgiVpnService.useEngine(context)) "client" else "engine"
                    if (next == "client") CorgiVpnService.stop(context)
                    vpnPrefs(context).edit().putString(CorgiVpnService.KEY_MODE, next).apply()
                    ui = ui.copy(engine = next == "engine", notice = if (next == "engine") t("vpn_mode_engine") else t("vpn_mode_client"))
                }
                "vpn_server" -> if (!CorgiVpnService.useEngine(context)) notice(t("vpn_engine_missing")) else dialog = "server"
                "split_tunnel" -> if (!CorgiVpnService.useEngine(context)) notice(t("vpn_engine_missing")) else dialog = "split"
                "refresh" -> refresh()
                "sign_out" -> signOut()
            }
        }
    }

    LaunchedEffect(Unit) {
        if (demo) {
            // Fixed demo data for screenshots; nothing is requested from a server.
            base = ""
            data = ShopData(
                dashboard = JSONObject("""{"user":{"id":42,"wallet_balance":"350.00","referral_code":"LUSI42","referral_balance":"120.00"},"subscription":{"id":1,"name":"Премиум · 12 месяцев","plan_id":3,"status":"active","expires_at":"2027-05-28"}}"""),
                profiles = JSONArray("""[{"id":1,"name":"Основная","plan":"Год","expires_at":"2027-05-28","is_primary":true}]"""),
                plans = JSONArray("""[{"id":1,"name":"1 месяц","price":"299.00","duration_days":30,"device_limit":3,"traffic_limit_gb":null},{"id":2,"name":"3 месяца","price":"549.00","duration_days":90,"device_limit":3,"traffic_limit_gb":null},{"id":3,"name":"12 месяцев","price":"1499.00","duration_days":365,"device_limit":5,"traffic_limit_gb":null}]"""),
                traffic = JSONObject("""{"available":true,"traffic_used_bytes":38000000000,"traffic_limit_bytes":null}"""),
                servers = JSONObject("""{"nodes":[{"name":"Амстердам","country":"NL","status":"online","users_online":33},{"name":"Франкфурт","country":"DE","status":"online","users_online":41},{"name":"Хельсинки","country":"FI","status":"online","users_online":12},{"name":"Стокгольм","country":"SE","status":"online","users_online":8}]}"""),
                routing = JSONObject("""{"recommendation":{"name":"Хельсинки","country":"FI"}}"""),
                devices = JSONArray("""[{"id":1,"name":"Pixel 9","platform":"android","status":"active"},{"id":2,"name":"MacBook","platform":"macos","status":"active"}]"""),
                family = JSONObject("""{"owned":[{"subscription_id":1,"name":"Год","seats":3,"used":2,"invite":{"code":"aB3x9Kq2","bot":"https://t.me/corgi_lusi_bot?start=family_aB3x9Kq2"},"members":[{"id":1,"name":"mama","synced":true}]}],"member_of":[]}"""),
                status = JSONObject("""{"status":"ok","servers":{"online":5,"total":5},"countries":[{"country":"DE","online":2,"total":2},{"country":"NL","online":1,"total":1},{"country":"FI","online":2,"total":2}],"components":[],"incidents":[]}"""),
                notifications = JSONArray("""[{"id":1,"title":"Подписка продлена","body":"Спасибо! Следующее списание — 28 мая 2027","read":false}]"""),
                docs = JSONArray("""[{"kind":"faq","title":"Частые вопросы"},{"kind":"rules","title":"Правила"},{"kind":"privacy","title":"Политика конфиденциальности"},{"kind":"offer","title":"Публичная оферта"}]"""),
                giveaways = JSONArray("""[{"id":7,"title":"Новогоднее колесо","description":"Крутите колесо — до 1000 ₽ на баланс","kind":"wheel","phase":"open","prizes":[{"amount":"100","weight":5},{"amount":"1000","weight":1}],"currency":"RUB","ends_at":"2026-12-31T21:00:00Z","my_entry":null},{"id":6,"title":"Розыгрыш года подписки","description":"Три победителя получат год Премиума","kind":"contest","phase":"ended","prizes":[{"amount":"1499","weight":1}],"currency":"RUB","ends_at":"2026-10-20T21:00:00Z","my_entry":{"outcome":"won","reward_amount":"1499.00"}}]"""),
            )
            ui = ui.copy(vpn = if (flag(intent(activity), "corgi_vpn_on")) VpnState.ON else VpnState.OFF)
        }
    }
    LaunchedEffect(token) {
        if (demo) return@LaunchedEffect
        if (token.isNotBlank() && !unlocked) promptUnlock(activity, t("unlock")) { unlocked = it }
    }
    // Analytics follow the «analytics» layout feature; the first launch and every screen are counted.
    LaunchedEffect(layout) { CorgiAnalytics.enabled = layout.feature("analytics") }
    LaunchedEffect(base) {
        if (demo || base.isBlank()) return@LaunchedEffect
        CorgiAnalytics.install(context, base)
        track("open")
    }
    LaunchedEffect(tab, token) {
        if (token.isBlank()) track("sign_in_view") else track("screen", tab)
    }
    LaunchedEffect(ui.vpn) {
        if (ui.vpn != VpnState.ON) return@LaunchedEffect
        track("connected")
        // Xiaomi, Samsung, Huawei… stop background VPNs: once per version, explain how to keep it on.
        if (!demo && ui.engine && dialog.isEmpty() && shop.remnawave.user.vpn.BatteryGuard.shouldHint(context, ui.version)) {
            shop.remnawave.user.vpn.BatteryGuard.markShown(context, ui.version)
            dialog = "battery"
        }
    }
    LaunchedEffect(token, lang, unlocked) {
        if (demo) return@LaunchedEffect
        if (token.isNotBlank() && unlocked) refresh()
    }
    LaunchedEffect(base) {
        val normalized = try { normalizeBase(base) } catch (_: Exception) { return@LaunchedEffect }
        if (token.isBlank()) { loadLayout(normalized); loadLogo(normalized); loadMethods(normalized) }
    }
    val pushTab by MainActivity.pendingTab
    LaunchedEffect(pushTab, layout) {
        val target = pushTab ?: return@LaunchedEffect
        if (layout.section(target) != null) { tab = target; openDoc = null; MainActivity.pendingTab.value = null }
    }
    val paidOrder by MainActivity.pendingPayment
    LaunchedEffect(paidOrder, token) {
        val order = paidOrder ?: return@LaunchedEffect
        if (demo || token.isBlank()) return@LaunchedEffect
        MainActivity.pendingPayment.value = null
        // The payment page is behind us: the webhook may still be on its way, so ask a few times.
        work {
            var state = "pending"
            for (attempt in 0 until 6) {
                val row = ShopApi(base, token, lang).get("/api/me/payments/order/" + Uri.encode(order)) as JSONObject
                state = row.optString("state", "pending")
                if (state != "pending" && state != "processing") break
                Thread.sleep(2500)
            }
            activity.runOnUiThread {
                notice(t(when (state) { "paid" -> "payment_done"; "failed" -> "payment_failed"; "refunded" -> "payment_refunded"; else -> "payment_waiting" }))
                if (state == "paid") track("checkout_done")
                refresh()
            }
        }
    }
    val pending by MainActivity.pendingLogin
    LaunchedEffect(pending) {
        val link = pending ?: return@LaunchedEffect
        MainActivity.pendingLogin.value = null
        if (demo) return@LaunchedEffect
        if (token.isNotBlank()) { notice(t("login_link_signed_in")); return@LaunchedEffect }
        redeemLink(link)
    }

    val theme = layout.theme
    MaterialTheme(colorScheme = colorScheme(theme)) {
        Box(Modifier.fillMaxSize().background(theme.background)) {
            when {
                token.isBlank() -> LoginScreen(layout, base, email, password, ui, ::t, logo,
                    showBase = bakedBase.isBlank(), methods = methods,
                    onProvider = { provider ->
                        if (provider == "telegram") methods.optString("telegram_url").takeIf { it.startsWith("https://t.me/") }?.let { openExternal(it) }
                        else openOAuth(provider)
                    },
                    onBase = { base = it }, onEmail = { email = it }, onPassword = { password = it },
                    onSignIn = { register ->
                        val normalized = try { normalizeBase(base) } catch (_: Exception) { notice(t("https_required")); return@LoginScreen }
                        if (!email.contains("@") || !email.contains(".")) { notice(t("email_invalid")); return@LoginScreen }
                        if (password.length < 8) { notice(t("password_short")); return@LoginScreen }
                        work {
                            val api = ShopApi(normalized, "", lang)
                            val body = JSONObject().put("email", email.trim()).put("password", password)
                            val response = api.post(if (register) "/api/auth/register" else "/api/auth/login", body) as JSONObject
                            val issued = response.optString("access_token")
                            if (issued.isBlank()) throw IllegalStateException("HTTP")
                            tokenStore.write(issued, normalized)
                            activity.runOnUiThread { saveSession(normalized, issued) }
                        }
                    },
                    onPasskey = {
                        // Discoverable passkey: no email or password needed, only the shop address.
                        val normalized = try { normalizeBase(base) } catch (_: Exception) { notice(t("https_required")); return@LoginScreen }
                        work {
                            val issued = try {
                                CorgiPasskeys.signIn(activity, normalized, lang)
                            } catch (_: CorgiPasskeys.Cancelled) {
                                activity.runOnUiThread { notice(t("passkey_cancelled")) }
                                return@work
                            } catch (_: CorgiPasskeys.NoPasskey) {
                                throw IllegalStateException(t("passkey_none"))
                            }
                            tokenStore.write(issued, normalized)
                            activity.runOnUiThread { saveSession(normalized, issued) }
                        }
                    },
                    onLanguage = {
                        lang = nextLanguage(lang)
                        prefs.edit().putString("lang", lang).apply()
                        layout = LayoutStore.cached(context, base, lang) ?: LayoutStore.bundled(context, lang)
                    })
                !unlocked -> Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(layout.text("brand"), color = theme.accent, fontSize = 34.sp, fontWeight = FontWeight.Black)
                    Spacer(Modifier.height(24.dp))
                    ActionButton(LayoutButton("unlock", t("unlock"), "refresh", "", "primary", "lock", "any"), theme) { promptUnlock(activity, t("unlock")) { unlocked = it } }
                    Spacer(Modifier.height(12.dp))
                    ActionButton(LayoutButton("sign_out", t("sign_out"), "sign_out", "", "ghost", "logout", "any"), theme) { signOut() }
                }
                else -> Column(Modifier.fillMaxSize()) {
                    val section = layout.section(tab) ?: layout.section(layout.tabs.firstOrNull { layout.section(it)?.kind == "vpn" } ?: "") ?: layout.sections.first()
                    Box(Modifier.weight(1f)) {
                        val doc = openDoc
                        if (doc != null) { DocumentScreen(layout, base, doc, onBack = { openDoc = null }, onLink = { openExternal(it) }); return@Box }
                        SectionScreen(layout, section, base, data, ui.copy(languageLabel = currentLanguageLabel(lang)), actions)
                        if (!section.tab) TextButton(onClick = { tab = layout.tabs.firstOrNull { layout.section(it)?.kind == "vpn" } ?: layout.tabs.first() },
                            modifier = Modifier.statusBarsPadding().padding(4.dp)) { Text("←", color = theme.text, fontSize = 22.sp) }
                    }
                    BottomBar(layout, if (section.tab) section.id else "", onSelect = { tab = it; openDoc = null; ui = ui.copy(notice = "") })
                }
            }
            if (dialog == "server") ServerDialog(layout, ::t, onClose = { dialog = "" }) { name ->
                vpnPrefs(context).edit().apply { if (name.isBlank()) remove(CorgiVpnService.KEY_SERVER) else putString(CorgiVpnService.KEY_SERVER, name) }.apply()
                dialog = ""; notice(if (name.isBlank()) t("vpn_server_auto") else name); restartEngine()
            }
            if (dialog == "split") SplitDialog(layout, ::t, onClose = { dialog = ""; restartEngine() })
            if (dialog == "battery") BatteryDialog(layout, ::t, onClose = { dialog = "" })
            if (dialog != "server" && dialog != "split" && dialog != "battery") ShopDialog(dialog, layout, data, ::t, dialogText, dialogText2, { dialogText = it }, { dialogText2 = it }, onClose = { dialog = "" }) { kind ->
                when {
                    kind == "redeem" -> { val code = dialogText.trim().uppercase(); work {
                        ShopApi(base, token, lang).post("/api/me/gifts/redeem", JSONObject().put("code", code))
                        activity.runOnUiThread { notice(t("gift_ok")); refresh() } } }
                    kind == "ticket" || kind == "report" -> {
                        val subject = if (kind == "report") t("report_subject") else dialogText2.trim()
                        val message = if (kind == "report") "${dialogText.trim()}\n\n— ${ui.version} · Android ${android.os.Build.VERSION.RELEASE} · VPN ${ui.vpn}" else dialogText.trim()
                        if (subject.isNotBlank() && message.isNotBlank()) work {
                            ShopApi(base, token, lang).post("/api/me/support/tickets", JSONObject().put("subject", subject).put("message", message))
                            activity.runOnUiThread { notice(t("ticket_sent")) }
                        }
                    }
                    kind == "passkey_add" -> { val current = dialogText; work {
                        try {
                            CorgiPasskeys.register(activity, base, token, lang, current, android.os.Build.MODEL.take(60).ifBlank { "Android" })
                        } catch (_: CorgiPasskeys.Cancelled) {
                            activity.runOnUiThread { notice(t("passkey_cancelled")) }
                            return@work
                        }
                        activity.runOnUiThread { notice(t("passkey_added")); refresh() } } }
                    kind.startsWith("passkey_delete:") -> { val id = kind.substringAfter(":").toIntOrNull() ?: 0; val current = dialogText; work {
                        CorgiPasskeys.delete(base, token, lang, id, current)
                        activity.runOnUiThread { notice(t("passkey_deleted")); refresh() } } }
                }
                dialog = ""
            }
        }
    }
}

private fun intent(activity: FragmentActivity): Intent = activity.intent ?: Intent()

/** A demo/test switch: `--ez name true` from adb, or the string "true" that Maestro launch arguments pass. */
internal fun flag(intent: Intent?, name: String): Boolean {
    val extras = intent?.extras ?: return false
    return when (val value = extras.get(name)) {
        is Boolean -> value
        is String -> value.equals("true", ignoreCase = true)
        else -> false
    }
}

private fun vpnPrefs(context: android.content.Context) = context.getSharedPreferences(CorgiVpnService.PREFS, 0)

/** «Сервер VPN» of the embedded engine: automatic (fastest) or one server of the subscription. */
@Composable
private fun ServerDialog(layout: AppLayout, t: (String) -> String, onClose: () -> Unit, onPick: (String) -> Unit) {
    val theme = layout.theme
    val context = LocalContext.current
    val servers = remember { CorgiVpnService.servers(context) }
    val current = remember { vpnPrefs(context).getString(CorgiVpnService.KEY_SERVER, "").orEmpty() }
    AlertDialog(onDismissRequest = onClose, containerColor = theme.surface, titleContentColor = theme.text, textContentColor = theme.text,
        title = { Text(t("vpn_server")) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ActionButton(LayoutButton("auto", (if (current.isBlank()) "✓ " else "") + t("vpn_server_auto"), "refresh", "", if (current.isBlank()) "primary" else "secondary", "rocket", "any"), theme) { onPick("") }
                if (servers.isEmpty()) Muted(t("vpn_servers_empty"), theme)
                servers.forEach { name ->
                    ActionButton(LayoutButton("s", (if (name == current) "✓ " else "") + name, "refresh", "", if (name == current) "primary" else "secondary", "globe", "any"), theme) { onPick(name) }
                }
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text(t("done"), color = theme.accent) } })
}

/** «VPN отключается в фоне»: on Xiaomi/Samsung/Huawei… firmware, how to keep the tunnel on. */
@Composable
private fun BatteryDialog(layout: AppLayout, t: (String) -> String, onClose: () -> Unit) {
    val theme = layout.theme
    val context = LocalContext.current
    val guard = shop.remnawave.user.vpn.BatteryGuard
    val vendorScreens = remember { guard.vendorIntents(context) }
    AlertDialog(onDismissRequest = onClose, containerColor = theme.surface, titleContentColor = theme.text, textContentColor = theme.text,
        title = { Text(t("battery_title")) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(t("battery_body").replace("{vendor}", android.os.Build.MANUFACTURER.replaceFirstChar { it.uppercase() }))
                ActionButton(LayoutButton("battery", t("battery_open"), "refresh", "", "primary", "power", "any"), theme) {
                    guard.open(context, guard.batteryIntents(context)); onClose()
                }
                if (vendorScreens.isNotEmpty()) ActionButton(LayoutButton("autostart", t("battery_autostart"), "refresh", "", "secondary", "rocket", "any"), theme) {
                    if (!guard.open(context, vendorScreens)) guard.open(context, guard.batteryIntents(context)); onClose()
                }
                ActionButton(LayoutButton("guide", t("battery_guide"), "refresh", "", "secondary", "globe", "any"), theme) {
                    guard.open(context, listOf(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(guard.GUIDE + guard.vendor())))); onClose()
                }
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text(t("later"), color = theme.accent) } })
}

/** «Что работает без VPN»: apps and Russian sites that bypass the embedded VPN. */
@Composable
private fun SplitDialog(layout: AppLayout, t: (String) -> String, onClose: () -> Unit) {
    val theme = layout.theme
    val context = LocalContext.current
    val prefs = remember { vpnPrefs(context) }
    val apps = remember {
        val pm = context.packageManager
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        pm.queryIntentActivities(launcher, 0).map { it.activityInfo.packageName to it.loadLabel(pm).toString() }
            .filter { it.first != context.packageName }.distinctBy { it.first }.sortedBy { it.second.lowercase() }
    }
    var excluded by remember { mutableStateOf(CorgiVpnService.excludedApps(context)) }
    var bypassRu by remember { mutableStateOf(prefs.getBoolean(CorgiVpnService.KEY_BYPASS_RU, false)) }
    AlertDialog(onDismissRequest = onClose, containerColor = theme.surface, titleContentColor = theme.text, textContentColor = theme.text,
        title = { Text(t("split_title")) },
        text = {
            Column(Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Muted(t("split_hint"), theme)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(bypassRu, { bypassRu = it; prefs.edit().putBoolean(CorgiVpnService.KEY_BYPASS_RU, it).apply() })
                    Text(t("bypass_ru"), color = theme.text)
                }
                apps.forEach { (pkg, label) ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(pkg in excluded, { on ->
                            excluded = if (on) excluded + pkg else excluded - pkg
                            prefs.edit().putStringSet(CorgiVpnService.KEY_EXCLUDED, excluded).apply()
                        })
                        Text(label, color = theme.text)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text(t("done"), color = theme.accent) } })
}

private fun currentLanguageLabel(lang: String): String = when (lang) { "en" -> "English"; "uk" -> "Українська"; else -> "Русский" }

/** Sign-in screen in the brand colours of the layout. */
@Composable
private fun LoginScreen(
    layout: AppLayout, base: String, email: String, password: String, ui: UiFlags, t: (String) -> String, logo: ImageBitmap?,
    showBase: Boolean, methods: JSONObject, onProvider: (String) -> Unit,
    onBase: (String) -> Unit, onEmail: (String) -> Unit, onPassword: (String) -> Unit,
    onSignIn: (Boolean) -> Unit, onPasskey: () -> Unit, onLanguage: () -> Unit,
) {
    val theme = layout.theme
    Column(
        Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(22.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            if (logo != null) { Image(logo, contentDescription = null, modifier = Modifier.size(44.dp)); Spacer(Modifier.width(12.dp)) }
            Text(layout.text("brand"), color = theme.accent, fontSize = 30.sp, fontWeight = FontWeight.Black, modifier = Modifier.weight(1f))
            if (layout.feature("language_switch")) TextButton(onClick = onLanguage) { Text(languageLabel(layout.lang), color = theme.muted) }
        }
        if (layout.feature("login_banner")) SectionBanner(base, layout.sections.firstOrNull { it.kind == "vpn" }?.banner, theme) { }
        Text(t("welcome"), color = theme.text, fontSize = 26.sp, fontWeight = FontWeight.Bold)
        Muted(t("tagline"), theme)
        if (ui.notice.isNotBlank()) Text(ui.notice, color = theme.accent2)
        if (showBase) TextInput(base, onBase, t("server"), theme)
        // Quick sign-in: Telegram bot link and OAuth providers enabled on the shop.
        if (layout.feature("login_quick")) {
            if (methods.optBoolean("telegram")) ActionButton(LayoutButton("login_telegram", t("login_telegram"), "refresh", "", "primary", "send", "any"), theme, enabled = !ui.busy) { onProvider("telegram") }
            listOf("yandex", "vk", "google").filter { methods.optBoolean(it) }.forEach { provider ->
                ActionButton(LayoutButton("login_$provider", t("login_$provider"), "refresh", "", "secondary", "user", "any"), theme, enabled = !ui.busy) { onProvider(provider) }
            }
            if (methods.optBoolean("telegram") || methods.optBoolean("yandex") || methods.optBoolean("vk") || methods.optBoolean("google")) Muted(t("login_or_email"), theme)
        }
        TextInput(email, onEmail, t("email"), theme)
        TextInput(password, onPassword, t("password"), theme, secret = true)
        ActionButton(LayoutButton("sign_in", t("sign_in"), "refresh", "", "primary", "user", "any"), theme, enabled = !ui.busy) { onSignIn(false) }
        if (layout.feature("login_sign_up")) ActionButton(LayoutButton("sign_up", t("sign_up"), "refresh", "", "secondary", "plus", "any"), theme, enabled = !ui.busy) { onSignIn(true) }
        if (layout.feature("login_passkey")) ActionButton(LayoutButton("passkey", t("passkey_sign_in"), "refresh", "", "ghost", "key", "any"), theme, enabled = !ui.busy) { onPasskey() }
    }
}

/** Dialogs: QR code, VPN client install, promo code, support message, problem report, passkeys. */
@Composable
private fun ShopDialog(
    kind: String, layout: AppLayout, data: ShopData, t: (String) -> String, text: String, text2: String,
    onText: (String) -> Unit, onText2: (String) -> Unit, onClose: () -> Unit, onConfirm: (String) -> Unit,
) {
    if (kind.isBlank()) return
    val theme = layout.theme
    val context = LocalContext.current
    AlertDialog(
        onDismissRequest = onClose,
        containerColor = theme.surface,
        titleContentColor = theme.text,
        textContentColor = theme.text,
        title = {
            Text(when {
                kind == "qr" -> t("qr")
                kind == "install" -> t("vpn_install")
                kind == "redeem" -> t("gift_code")
                kind == "ticket" -> t("support")
                kind == "report" -> t("report_subject")
                kind == "passkey_add" -> t("passkey_add")
                else -> t("passkey_delete")
            })
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                when {
                    kind == "qr" -> QrCard(data, theme)
                    kind == "install" -> {
                        Muted(t("vpn_install_hint"), theme)
                        VpnClients.CLIENTS.forEach { client ->
                            ActionButton(LayoutButton(client.id, client.title, "url", client.store, "secondary", "download", "any"), theme) {
                                try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(client.store))) } catch (_: ActivityNotFoundException) { }
                            }
                        }
                    }
                    kind == "redeem" -> TextInput(text, onText, t("code"), theme)
                    kind == "ticket" -> { TextInput(text2, onText2, t("subject"), theme); TextInput(text, onText, t("message"), theme, singleLine = false) }
                    kind == "report" -> { Muted(t("report_hint"), theme); TextInput(text, onText, t("message"), theme, singleLine = false) }
                    else -> TextInput(text, onText, t("current_password"), theme, secret = true)
                }
            }
        },
        confirmButton = {
            if (kind != "qr" && kind != "install") TextButton(onClick = { onConfirm(kind) }) { Text(if (kind == "redeem") t("redeem") else t("send").takeIf { kind in setOf("ticket", "report") } ?: t("done"), color = theme.accent) }
        },
        dismissButton = { TextButton(onClick = onClose) { Text(if (kind == "qr" || kind == "install") t("done") else t("cancel"), color = theme.muted) } },
    )
}

private fun loadAuthedPng(base: String, path: String, token: String, lang: String): ImageBitmap? {

    val connection = (URL(base + path).openConnection() as HttpURLConnection).apply {
        instanceFollowRedirects = false
        connectTimeout = 15000
        readTimeout = 15000
        setRequestProperty("Accept", "image/png")
        setRequestProperty("Accept-Language", lang)
        setRequestProperty("User-Agent", "CorgiLusi-Android-User/3.1.0")
        setRequestProperty("X-Shop-Client", "android-user")


        if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token")
    }
    if (connection.responseCode !in 200..299) return null
    val bytes = connection.inputStream.use { it.readBytes() }
    if (bytes.size > 2 * 1024 * 1024) return null
    return android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
}

private fun providerOf(config: JSONObject): String {
    val providers = config.optJSONArray("payment_providers") ?: JSONArray()
    for (index in 0 until providers.length()) {
        val name = providers.optString(index)
        if (name.equals("sandbox", true)) return name
    }
    return if (providers.length() > 0) providers.optString(0) else ""
}

private fun pickOptions(options: JSONArray): JSONObject {
    val picked = JSONObject()
    for (kind in listOf("devices", "traffic_gb", "days")) {
        for (index in 0 until options.length()) {
            val option = options.getJSONObject(index)
            if (option.optString("kind") == kind && option.optBoolean("enabled", true) && !picked.has(kind)) picked.put(kind, option.optInt("id"))
        }
    }
    return picked
}

private fun loadStrings(context: android.content.Context, lang: String): JSONObject {
    val text = context.assets.open("l10n.json").bufferedReader().use { it.readText() }
    return JSONObject(text).getJSONObject(lang)
}

private fun autoLanguage(): String = when (Locale.getDefault().language.lowercase(Locale.ROOT)) {
    "uk" -> "uk"
    "en" -> "en"
    else -> "ru"
}

private fun nextLanguage(current: String): String = when (current) {
    "ru" -> "en"
    "en" -> "uk"
    else -> "ru"
}

private fun languageLabel(current: String): String = when (current) {
    "ru" -> "EN"
    "en" -> "UK"
    else -> "RU"
}
