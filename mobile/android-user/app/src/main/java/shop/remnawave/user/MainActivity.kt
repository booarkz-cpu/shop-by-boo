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
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        // A tapped push opens the notification center (FCM puts the data payload into extras).
        val initialTab = if (intent?.hasExtra(CorgiPush.EXTRA_TAB) == true || intent?.hasExtra("notification_id") == true) "notifications" else "overview"
        setContent { MaterialTheme(colorScheme = shopColors()) { UserApp(initialTab) } }
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
        val verifier = if (path in setOf("/api/auth/login", "/api/auth/register", "/api/admin/auth/login", "/api/auth/passkeys/login/verify")) pkceVerifier() else null
        val connection = (URL(base + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            instanceFollowRedirects = false
            connectTimeout = 15000
            readTimeout = 15000
            setRequestProperty("Accept", "application/json")
            if (verifier != null) setRequestProperty("X-Shop-Code-Challenge", pkceChallenge(verifier))
            setRequestProperty("Accept-Language", lang)
            setRequestProperty("User-Agent", "CorgiLusi-Android-User/2.15.0")
            // Historical compatibility marker: CorgiLusi-Android-User/2.9.0
            setRequestProperty("X-Shop-Client", "android-user")


            if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token")
            if (idempotency != null) setRequestProperty("Idempotency-Key", idempotency)
            headers.forEach { (name, value) -> setRequestProperty(name, value) }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                outputStream.use { it.write(body.toString().toByteArray()) }
            }
        }
        val code = connection.responseCode
        val text = (if (code in 200..299) connection.inputStream else connection.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code !in 200..299) throw IllegalStateException(detailOf(text, code))
        val trimmed = text.trim()
        val result: Any = if (trimmed.startsWith("[")) JSONArray(trimmed) else JSONObject(if (trimmed.isBlank()) "{}" else trimmed)
        if (verifier != null && result is JSONObject && result.has("authorization_code")) {
            val exchanged = post("/api/auth/mobile/token", JSONObject().put("code", result.getString("authorization_code")).put("code_verifier", verifier)) as JSONObject
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
private fun UserApp(initialTab: String = "overview") {
    val context = LocalContext.current
    val activity = context as FragmentActivity
    val prefs = remember { context.getSharedPreferences("shop_user", 0) }
    val tokenStore = remember { SecureTokenStore(prefs) }
    var lang by remember { mutableStateOf(prefs.getString("lang", null) ?: autoLanguage()) }
    var base by remember { mutableStateOf(prefs.getString("base", "") ?: "") }
    var token by remember { mutableStateOf(tokenStore.read()) }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var tab by remember { mutableStateOf(initialTab) }
    var notice by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var dashboard by remember { mutableStateOf(JSONObject()) }
    var profiles by remember { mutableStateOf(JSONArray()) }
    var plans by remember { mutableStateOf(JSONArray()) }
    var builders by remember { mutableStateOf(JSONArray()) }
    var servers by remember { mutableStateOf(JSONObject()) }
    var connection by remember { mutableStateOf(JSONObject()) }
    var config by remember { mutableStateOf(JSONObject()) }
    var logo by remember { mutableStateOf<ImageBitmap?>(null) }
    var promo by remember { mutableStateOf("") }
    var devices by remember { mutableStateOf(JSONArray()) }
    var traffic by remember { mutableStateOf(JSONObject()) }
    var notifications by remember { mutableStateOf(JSONArray()) }
    var routing by remember { mutableStateOf(JSONObject()) }
    var features by remember { mutableStateOf(JSONObject()) }
    var diagnostics by remember { mutableStateOf(JSONObject()) }
    var privacy by remember { mutableStateOf(JSONObject()) }
    var mobileConnection by remember { mutableStateOf(JSONObject()) }
    var giftCode by remember { mutableStateOf("") }
    var topupAmount by remember { mutableStateOf("100") }
    var qr by remember { mutableStateOf<ImageBitmap?>(null) }
    var unlocked by remember { mutableStateOf(token.isBlank()) }
    var pushEnabled by remember { mutableStateOf(CorgiPush.enabled(context)) }
    var widgetEnabled by remember { mutableStateOf(CorgiWidgetData.enabled(context)) }
    var passkeys by remember { mutableStateOf(JSONArray()) }
    var passkeyPassword by remember { mutableStateOf("") }
    var family by remember { mutableStateOf(JSONObject()) }
    var familyCode by remember { mutableStateOf("") }
    var serviceStatus by remember { mutableStateOf(JSONObject()) }
    DisposableEffect(activity) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) unlocked = false
        }
        activity.lifecycle.addObserver(observer)
        onDispose { activity.lifecycle.removeObserver(observer) }
    }

    var subject by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    val strings = remember(lang) { loadStrings(context, lang) }
    fun t(key: String) = strings.optString(key, key)
    fun saveSession(nextBase: String, nextToken: String) {
        base = nextBase
        token = nextToken
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
        pushEnabled = false
        widgetEnabled = false
        CorgiWidgetData.clear(context)
        thread {
            // Revoke the push token while the session is still valid, then end the session.
            CorgiPush.unregister(context, origin, previous, lang)
            try {
                if (previous.isNotBlank()) ShopApi(origin, previous, lang).post("/api/auth/logout", JSONObject())
            } catch (_: Exception) {
                activity.runOnUiThread { notice = "Signed out locally; server session revocation could not be confirmed." }
            }
        }
    }
    fun work(block: () -> Unit) {
        busy = true
        notice = ""
        thread {
            val error = try { block(); null } catch (exc: Exception) { exc.message ?: "HTTP" }
            activity.runOnUiThread {
                busy = false
                if (error != null) notice = error
            }
        }
    }
    fun enablePush() {
        work {
            if (!CorgiPush.buildSupportsPush()) throw IllegalStateException(t("push_unavailable"))
            val response = CorgiPush.register(context, base, token, lang)
            activity.runOnUiThread {
                pushEnabled = true
                notice = if (response.optBoolean("push_available")) t("push_on") else t("push_server_off")
            }
        }
    }
    val notificationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            enablePush()
        } else {
            notice = t("push_denied")
        }
    }
    fun refresh() {
        val api = ShopApi(base, token, lang)
        work {
            // Re-bind the push token to the current session (tokens rotate, sessions are re-issued).
            if (CorgiPush.enabled(context) && CorgiPush.permissionGranted(context)) {
                try { CorgiPush.register(context, base, token, lang) } catch (_: Exception) { }
            }
            if (CorgiWidgetData.enabled(context)) CorgiWidgetData.refresh(context)
            val nextDashboard = api.get("/api/me/dashboard") as JSONObject
            val nextProfiles = api.get("/api/me/subscriptions") as JSONArray
            val nextPlans = api.get("/api/plans") as JSONArray
            val nextBuilders = api.get("/api/tariff-constructors") as JSONArray
            val nextServers = api.get("/api/me/servers") as JSONObject
            val nextConnection = api.get("/api/me/connection-info") as JSONObject
            val nextConfig = api.get("/api/public/config") as JSONObject
            val nextTraffic = api.get("/api/me/traffic") as JSONObject
            val nextDevices = api.get("/api/me/devices") as JSONArray
            val nextNotifications = api.get("/api/me/mobile/notifications?unread_only=false") as JSONArray
            val nextRouting = api.get("/api/me/routing/recommendation") as JSONObject
            val nextFeatures = api.get("/api/me/mobile/features") as JSONObject
            val nextDiagnostics = api.get("/api/me/mobile/diagnostics") as JSONObject
            val nextPrivacy = api.get("/api/me/mobile/privacy") as JSONObject
            val nextConnectionLive = api.get("/api/me/mobile/connection") as JSONObject
            val nextQr = loadAuthedPng(base, "/api/me/connection-qr", token, lang)
            // Shops on releases before v28.25.0 have no family or status page: keep the rest working.
            val nextFamily = try { api.get("/api/me/family") as JSONObject } catch (_: Exception) { JSONObject() }
            val nextStatus = try { api.get("/api/public/service-status") as JSONObject } catch (_: Exception) { JSONObject() }
            val nextLogo = try {
                val catalog = api.get("/api/public/apps") as JSONObject
                loadLogoBitmap(base, catalog.optString("logo_url"))?.asImageBitmap()
            } catch (_: Exception) { null }
            activity.runOnUiThread {
                dashboard = nextDashboard
                profiles = nextProfiles
                plans = nextPlans
                builders = nextBuilders
                servers = nextServers
                connection = nextConnection
                config = nextConfig
                traffic = nextTraffic
                devices = nextDevices
                notifications = nextNotifications
                routing = nextRouting
                features = nextFeatures
                diagnostics = nextDiagnostics
                privacy = nextPrivacy
                mobileConnection = nextConnectionLive
                qr = nextQr
                family = nextFamily
                serviceStatus = nextStatus
                logo = nextLogo
            }
        }
    }
    LaunchedEffect(token) {
        if (token.isNotBlank() && !unlocked) promptUnlock(activity, t("unlock")) { unlocked = it }
    }
    LaunchedEffect(token, lang, unlocked) {
        if (token.isNotBlank() && unlocked) refresh()
    }
    LaunchedEffect(base) {
        val normalized = try { normalizeBase(base) } catch (_: Exception) { return@LaunchedEffect }
        if (token.isNotBlank()) return@LaunchedEffect
        thread {
            try {
                val catalog = ShopApi(normalized, "", lang).get("/api/public/apps") as JSONObject
                val nextLogo = loadLogoBitmap(normalized, catalog.optString("logo_url"))?.asImageBitmap()
                activity.runOnUiThread { logo = nextLogo }
            } catch (_: Exception) {
            }
        }
    }
    Scaffold { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                if (logo != null) Image(logo!!, contentDescription = t("app_name"), modifier = Modifier.size(48.dp))
                Text(t("app_name"), style = MaterialTheme.typography.headlineSmall, color = Color(0xFF8A79FF))
                TextButton(onClick = {
                    lang = nextLanguage(lang)
                    prefs.edit().putString("lang", lang).apply()
                }) { Text(languageLabel(lang)) }
            }
            Text(t("tagline"), color = Color(0xFFA4AFD0))
            if (notice.isNotBlank()) Text(notice, color = Color(0xFFFFB020))
            if (token.isBlank()) {
                OutlinedTextField(base, { base = it }, label = { Text(t("server")) }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(email, { email = it }, label = { Text(t("email")) }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(password, { password = it }, label = { Text(t("password")) }, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                Button(onClick = {
                    val normalized = try { normalizeBase(base) } catch (_: Exception) { notice = t("https_required"); return@Button }
                    if (!email.contains("@") || !email.contains(".")) { notice = t("email_invalid"); return@Button }
                    if (password.length < 8) { notice = t("password_short"); return@Button }
                    work {
                        val api = ShopApi(normalized, "", lang)
                        val body = JSONObject().put("email", email.trim()).put("password", password)
                        val response = api.post("/api/auth/login", body) as JSONObject
                        val issued = response.optString("access_token")
                        if (issued.isBlank()) throw IllegalStateException("HTTP")
                        tokenStore.write(issued, normalized)
                        activity.runOnUiThread { saveSession(normalized, issued) }
                    }
                }, enabled = !busy) { Text(t("sign_in")) }
                TextButton(onClick = {
                    val normalized = try { normalizeBase(base) } catch (_: Exception) { notice = t("https_required"); return@TextButton }
                    if (!email.contains("@") || !email.contains(".")) { notice = t("email_invalid"); return@TextButton }
                    if (password.length < 8) { notice = t("password_short"); return@TextButton }
                    work {
                        val api = ShopApi(normalized, "", lang)
                        val body = JSONObject().put("email", email.trim()).put("password", password)
                        val response = api.post("/api/auth/register", body) as JSONObject
                        val issued = response.optString("access_token")
                        if (issued.isBlank()) throw IllegalStateException("HTTP")
                        tokenStore.write(issued, normalized)
                        activity.runOnUiThread { saveSession(normalized, issued) }
                    }
                }, enabled = !busy) { Text(t("sign_up")) }
                // Discoverable passkey: no email or password needed, only the shop address.
                TextButton(onClick = {
                    val normalized = try { normalizeBase(base) } catch (_: Exception) { notice = t("https_required"); return@TextButton }
                    work {
                        val issued = try {
                            CorgiPasskeys.signIn(activity, normalized, lang)
                        } catch (_: CorgiPasskeys.Cancelled) {
                            activity.runOnUiThread { notice = t("passkey_cancelled") }
                            return@work
                        } catch (_: CorgiPasskeys.NoPasskey) {
                            throw IllegalStateException(t("passkey_none"))
                        }
                        tokenStore.write(issued, normalized)
                        activity.runOnUiThread { saveSession(normalized, issued) }
                    }
                }, enabled = !busy) { Text(t("passkey_sign_in")) }
            } else if (!unlocked) {
                Button(onClick = { promptUnlock(activity, t("unlock")) { unlocked = it } }) { Text(t("unlock")) }
                TextButton(onClick = { signOut() }) { Text(t("sign_out")) }
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("overview", "plans", "builder", "servers", "connection", "family", "devices", "notifications", "status", "security", "diagnostics", "privacy", "support").forEach { key ->
                        FilterChip(selected = tab == key, onClick = { tab = key }, label = { Text(t(key)) })
                    }
                }
                TextButton(onClick = { refresh() }, enabled = !busy) { Text(t("refresh")) }
                TextButton(onClick = {
                    signOut()
                }) { Text(t("sign_out")) }
                when (tab) {
                    "overview" -> {
                        val user = dashboard.optJSONObject("user") ?: JSONObject()
                        val sub = dashboard.optJSONObject("subscription")
                        Text(t("my_subscriptions"))
                        for (profileIndex in 0 until profiles.length()) {
                            val profile = profiles.getJSONObject(profileIndex)
                            Text("${profile.optString("name")} · ${profile.optString("plan")} · ${profile.optString("expires_at")}")
                            if (profile.optBoolean("is_primary")) Text(t("selected_subscription"))
                            else Button(enabled = !busy, onClick = {
                                val profileId = profile.getInt("id")
                                work {
                                    ShopApi(base, token, lang).post("/api/me/subscriptions/$profileId/select", JSONObject())
                                    activity.runOnUiThread { refresh() }
                                }
                            }) { Text(t("select_subscription")) }
                        }
                        Text("${t("wallet")}: ${user.optString("wallet_balance", "0")}")
                        Text("${t("referral")}: ${user.optString("referral_code")}")
                        Text(if (sub == null) t("no_subscription") else "${t("subscription")}: ${t("active")} · ${t("expires")} ${sub.optString("expires_at")}")
                        val used = traffic.opt("traffic_used_bytes")
                        val limit = traffic.opt("traffic_limit_bytes")
                        Text("${t("traffic_used")}: ${if (traffic.optBoolean("available")) used else t("usage_unavailable")}")
                        Text("${t("traffic_limit")}: ${if (limit == null || limit == JSONObject.NULL) t("unlimited") else limit}")
                        OutlinedTextField(topupAmount, { topupAmount = it }, label = { Text(t("topup_amount")) }, modifier = Modifier.fillMaxWidth())
                        Button(onClick = {
                            val amount = topupAmount.trim()
                            work {
                                val body = JSONObject().put("amount", amount).put("provider", providerOf(config))
                                val response = ShopApi(base, token, lang).post("/api/me/wallet/topup", body, UUID.randomUUID().toString()) as JSONObject
                                val url = response.optString("url")
                                activity.runOnUiThread {
                                    notice = t("topup_ok")
                                    if (externalUrlAllowed(url)) context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                                }
                            }
                        }) { Text(t("topup")) }
                        OutlinedTextField(giftCode, { giftCode = it }, label = { Text(t("gift_code")) }, modifier = Modifier.fillMaxWidth())
                        Button(onClick = {
                            if (giftCode.isBlank()) return@Button
                            work {
                                ShopApi(base, token, lang).post("/api/me/gifts/redeem", JSONObject().put("code", giftCode.trim().uppercase()))
                                activity.runOnUiThread { notice = t("gift_ok"); giftCode = "" }
                            }
                        }) { Text(t("redeem")) }
                    }
                    "plans" -> {
                        OutlinedTextField(promo, { promo = it }, label = { Text(t("promo")) }, modifier = Modifier.fillMaxWidth())
                        for (index in 0 until plans.length()) {
                            val plan = plans.getJSONObject(index)
                            Text("${plan.optString("name")} · ${plan.opt("price")} · ${plan.opt("duration_days")} ${t("days")}")
                            Row {
                                Button(onClick = {
                                    work {
                                        val body = JSONObject().put("plan_id", plan.getInt("id")).put("provider", providerOf(config))
                                        dashboard.optJSONObject("subscription")?.optInt("id")?.takeIf { it > 0 }?.let { body.put("subscription_id", it) }
                                        if (promo.isNotBlank()) body.put("promo_code", promo.trim())
                                        val response = ShopApi(base, token, lang).post("/api/payments/create", body, UUID.randomUUID().toString()) as JSONObject
                                        val url = response.optString("url")
                                        activity.runOnUiThread {
                                            notice = t("payment_created")
                                            if (externalUrlAllowed(url)) {
                                                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                                            }
                                        }
                                    }
                                }) { Text(t("pay")) }
                                TextButton(onClick = {
                                    work {
                                        val body = JSONObject().put("plan_id", plan.getInt("id"))
                                        dashboard.optJSONObject("subscription")?.optInt("id")?.takeIf { it > 0 }?.let { body.put("subscription_id", it) }
                                        if (promo.isNotBlank()) body.put("promo_code", promo.trim())
                                        ShopApi(base, token, lang).post("/api/me/wallet/spend", body, UUID.randomUUID().toString())
                                        activity.runOnUiThread { notice = t("paid_wallet") }
                                    }
                                }) { Text(t("pay_wallet")) }
                            }
                        }
                    }
                    "builder" -> {
                        for (index in 0 until builders.length()) {
                            val row = builders.getJSONObject(index)
                            Text(row.optString("name"))
                            val options = row.optJSONArray("options") ?: JSONArray()
                            val picked = pickOptions(options)
                            Text("${t("devices")} / ${t("traffic")} / ${t("days")}: ${picked.keys().asSequence().joinToString()}")
                            Button(onClick = {
                                work {
                                    val body = JSONObject()
                                        .put("constructor_id", row.getInt("id"))
                                        .put("provider", providerOf(config))
                                        .put("device_option_id", picked.optInt("devices"))
                                        .put("traffic_option_id", picked.optInt("traffic_gb"))
                                        .put("days_option_id", picked.optInt("days"))
                                    dashboard.optJSONObject("subscription")?.optInt("id")?.takeIf { it > 0 }?.let { body.put("subscription_id", it) }
                                    val response = ShopApi(base, token, lang).post("/api/payments/create", body, UUID.randomUUID().toString()) as JSONObject
                                    val url = response.optString("url")
                                    activity.runOnUiThread {
                                        notice = t("payment_created")
                                        if (externalUrlAllowed(url)) {
                                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                                        }
                                    }
                                }
                            }) { Text(t("pay")) }
                        }
                    }
                    "servers" -> {
                        if (servers.optString("error").isNotBlank()) Text(t("panel_down"))
                        val nodes = servers.optJSONArray("nodes") ?: JSONArray()
                        val rec = routing.optJSONObject("recommendation")
                        if (rec != null) Text("${t("recommended")}: ${rec.optString("name")} · ${rec.optString("country")}")
                        if (nodes.length() == 0) Text(t("nodes_empty"))
                        for (index in 0 until nodes.length()) {
                            val node = publicNode(nodes.getJSONObject(index))
                            Text("${node.optString("name")} · ${node.optString("country")} · ${t(node.optString("status"))} · ${node.optInt("users_online")}")
                        }
                    }
                    "connection" -> {
                        val url = connection.optString("subscription_url")
                        Text(if (url.isBlank()) t("no_subscription") else url)
                        if (url.isNotBlank()) {
                            if (qr != null) Image(qr!!, contentDescription = t("qr"), modifier = Modifier.size(180.dp))
                            TextButton(onClick = {
                                context.getSystemService(android.content.ClipboardManager::class.java)?.setPrimaryClip(android.content.ClipData.newPlainText("subscription", url))
                                notice = t("copied")
                            }) { Text(t("copy")) }
                            subscriptionApps(url).forEach { (label, link) ->
                                TextButton(onClick = {
                                    try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link))) }
                                    catch (_: ActivityNotFoundException) { notice = label }
                                }) { Text(label) }
                            }
                        }
                        Text(t("guides"))
                        val platforms = connection.optJSONObject("platforms") ?: JSONObject()
                        for (key in listOf("android", "ios", "tv", "windows", "macos", "linux")) Text("$key: ${platforms.optString(key)}")
                        Button(onClick = {
                            val planId = if (plans.length() > 0) plans.getJSONObject(0).optInt("id") else 0
                            if (planId == 0) return@Button
                            work {
                                ShopApi(base, token, lang).post("/api/me/trial", JSONObject().put("plan_id", planId).put("days", config.optInt("trial_days", 3)))
                                activity.runOnUiThread { notice = t("trial_started") }
                            }
                        }) { Text(t("trial")) }
                    }
                    "notifications" -> {
                        Text(t("push_title"), style = MaterialTheme.typography.titleMedium)
                        if (!CorgiPush.buildSupportsPush()) Text(t("push_unavailable"), color = Color(0xFFA4AFD0))
                        else {
                            Text(if (pushEnabled) t("push_on") else t("push_off"), color = Color(0xFFA4AFD0))
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                if (pushEnabled) {
                                    TextButton(enabled = !busy, onClick = {
                                        val session = token
                                        work {
                                            CorgiPush.unregister(context, base, session, lang)
                                            activity.runOnUiThread { pushEnabled = false; notice = t("push_off") }
                                        }
                                    }) { Text(t("push_disable")) }
                                    TextButton(enabled = !busy, onClick = {
                                        work {
                                            ShopApi(base, token, lang).post("/api/me/push/test", JSONObject())
                                            activity.runOnUiThread { notice = t("push_test_sent") }
                                        }
                                    }) { Text(t("push_test")) }
                                } else {
                                    Button(enabled = !busy, onClick = {
                                        if (android.os.Build.VERSION.SDK_INT >= 33 && !CorgiPush.permissionGranted(context)) {
                                            notificationPermission.launch(android.Manifest.permission.POST_NOTIFICATIONS)
                                        } else enablePush()
                                    }) { Text(t("push_enable")) }
                                }
                            }
                        }
                        if (notifications.length() == 0) Text(t("no_notifications"))
                        for (index in 0 until notifications.length()) {
                            val n = notifications.getJSONObject(index)
                            Text("${n.optString("title")} · ${n.optString("body")}")
                            if (!n.optBoolean("read")) TextButton(onClick = { work { ShopApi(base, token, lang).post("/api/me/mobile/notifications/${n.optInt("id")}/read", JSONObject()); activity.runOnUiThread { notice = t("mark_read") ; refresh() } } }) { Text(t("mark_read")) }
                        }
                    }
                    "security" -> {
                        Text(t("widget_title"), style = MaterialTheme.typography.titleMedium)
                        Text(if (widgetEnabled) t("widget_on") else t("widget_off"), color = Color(0xFFA4AFD0))
                        if (widgetEnabled) {
                            TextButton(onClick = {
                                CorgiWidgetData.setEnabled(context, false)
                                widgetEnabled = false
                            }) { Text(t("widget_disable")) }
                        } else {
                            Button(enabled = !busy, onClick = {
                                CorgiWidgetData.setEnabled(context, true)
                                widgetEnabled = true
                                work { CorgiWidgetData.refresh(context) }
                            }) { Text(t("widget_enable")) }
                        }
                        Text(t("passkeys"), style = MaterialTheme.typography.titleMedium)
                        Text(t("passkeys_hint"), color = Color(0xFFA4AFD0))
                        LaunchedEffect(tab, token) {
                            if (tab == "security" && token.isNotBlank()) work {
                                val rows = CorgiPasskeys.list(base, token, lang)
                                activity.runOnUiThread { passkeys = rows }
                            }
                        }
                        for (i in 0 until passkeys.length()) {
                            val key = passkeys.getJSONObject(i)
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text(key.optString("name"))
                                TextButton(enabled = !busy, onClick = {
                                    work {
                                        CorgiPasskeys.delete(base, token, lang, key.optInt("id"), passkeyPassword)
                                        val rows = CorgiPasskeys.list(base, token, lang)
                                        activity.runOnUiThread { passkeys = rows; passkeyPassword = ""; notice = t("passkey_deleted") }
                                    }
                                }) { Text(t("passkey_delete")) }
                            }
                        }
                        if (passkeys.length() == 0) Text(t("passkeys_empty"), color = Color(0xFFA4AFD0))
                        OutlinedTextField(passkeyPassword, { passkeyPassword = it }, label = { Text(t("current_password")) },
                            visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                        Button(enabled = !busy, onClick = {
                            work {
                                try {
                                    CorgiPasskeys.register(activity, base, token, lang, passkeyPassword, android.os.Build.MODEL.take(60).ifBlank { "Android" })
                                } catch (_: CorgiPasskeys.Cancelled) {
                                    activity.runOnUiThread { notice = t("passkey_cancelled") }
                                    return@work
                                }
                                val rows = CorgiPasskeys.list(base, token, lang)
                                activity.runOnUiThread { passkeys = rows; passkeyPassword = ""; notice = t("passkey_added") }
                            }
                        }) { Text(t("passkey_add")) }
                        Text(t("security"))
                        Text("Biometric unlock: ON")
                        Text("Kill Switch: ON")
                        Text("Always-On VPN: ON")
                        Text("Auto Failover: ON")
                        Text("Trusted Networks: available")
                        Text("Split Tunneling: available")
                        Text("${t("recommended")}: ${routing.optJSONObject("recommendation")?.optString("name") ?: t("no_subscription")}")
                        Button(onClick = { promptUnlock(activity, t("unlock")) { unlocked = it } }) { Text(t("unlock")) }
                        Text("Profiles: Fastest · Gaming · Streaming · Privacy · Work")
                    }
                    "diagnostics" -> {
                        Text("Corgi Diagnostics", style = MaterialTheme.typography.titleLarge)
                        Text("${diagnostics.optString("overall", "unknown").uppercase()}")
                        val checks = diagnostics.optJSONArray("checks") ?: JSONArray()
                        for (i in 0 until checks.length()) {
                            val c = checks.getJSONObject(i)
                            Text("${c.optString("name")}: ${c.optString("status")} — ${c.optString("detail")}")
                        }
                        val live = mobileConnection
                        Text("Connection: ${live.optString("status")}")
                        Text("Server: ${live.optJSONObject("server")?.optString("name") ?: "—"}")
                        Text("Latency: ${live.opt("latency_ms") ?: "—"} ms")
                        Text("Packet loss: ${live.opt("packet_loss_percent") ?: "—"}%")
                    }
                    "privacy" -> {
                        Text("Privacy Dashboard", style = MaterialTheme.typography.titleLarge)
                        Text("DNS protected: ${privacy.optBoolean("dns_protected")}")
                        Text("IPv6 protected: ${privacy.optBoolean("ipv6_protected")}")
                        Text("Kill Switch: ${privacy.optBoolean("kill_switch")}")
                        Text("Protected traffic: ${privacy.opt("protected_traffic_bytes")}")
                        Text("VPN time: ${privacy.opt("vpn_time_seconds")} sec")
                        Text("Family Plan: available")
                        Text("Business VPN: available")
                        Text("Referral & Rewards: available")
                    }
                    "devices" -> {
                        if (devices.length() == 0) Text(t("no_devices"))
                        for (index in 0 until devices.length()) {
                            val device = devices.getJSONObject(index)
                            Text("${device.optString("name")} · ${device.optString("platform")} · ${device.optString("status")}")
                            if (device.optString("status") == "active") {
                                TextButton(onClick = {
                                    work {
                                        ShopApi(base, token, lang).post("/api/me/devices/${device.optInt("id")}/revoke", JSONObject())
                                        activity.runOnUiThread { notice = t("device_revoked") }
                                    }
                                }) { Text(t("revoke")) }
                            }
                        }
                    }
                    "family" -> {
                        val owned = family.optJSONArray("owned") ?: JSONArray()
                        val memberOf = family.optJSONArray("member_of") ?: JSONArray()
                        if (owned.length() == 0 && memberOf.length() == 0) Text(t("family_none"))
                        for (index in 0 until owned.length()) {
                            val group = owned.getJSONObject(index)
                            Text("${t("family_owned")}: ${group.optString("name")}", style = MaterialTheme.typography.titleMedium)
                            Text("${t("family_seats")}: ${group.optInt("used")} / ${group.optInt("seats")}")
                            val invite = group.optJSONObject("invite")
                            if (invite != null) {
                                Text("${t("family_code")}: ${invite.optString("code")}")
                                val link = invite.optString("bot")
                                if (link.isNotBlank()) TextButton(onClick = {
                                    context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, link), t("family_invite")))
                                }) { Text(link) }
                            } else Button(enabled = !busy, onClick = {
                                val subId = group.optInt("subscription_id")
                                work {
                                    ShopApi(base, token, lang).post("/api/me/family/$subId/invite", JSONObject())
                                    activity.runOnUiThread { refresh() }
                                }
                            }) { Text(t("family_invite")) }
                            val members = group.optJSONArray("members") ?: JSONArray()
                            for (m in 0 until members.length()) {
                                val member = members.getJSONObject(m)
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text("${member.optString("name")} · ${if (member.optBoolean("synced")) t("family_synced") else t("family_pending")}")
                                    TextButton(enabled = !busy, onClick = {
                                        val memberId = member.optInt("id")
                                        work {
                                            ShopApi(base, token, lang).delete("/api/me/family/members/$memberId")
                                            activity.runOnUiThread { refresh() }
                                        }
                                    }) { Text(t("family_remove")) }
                                }
                            }
                        }
                        for (index in 0 until memberOf.length()) {
                            val row = memberOf.getJSONObject(index)
                            Text("${t("family_member_of")} · ${t("family_owner")}: ${row.optString("owner")} · ${t("expires")} ${row.optString("expires_at")}")
                            TextButton(enabled = !busy, onClick = {
                                val memberId = row.optInt("id")
                                work {
                                    ShopApi(base, token, lang).delete("/api/me/family/members/$memberId")
                                    activity.runOnUiThread { refresh() }
                                }
                            }) { Text(t("family_leave")) }
                        }
                        OutlinedTextField(familyCode, { familyCode = it }, label = { Text(t("family_code")) }, modifier = Modifier.fillMaxWidth())
                        Button(enabled = !busy && familyCode.isNotBlank(), onClick = {
                            val code = familyCode.trim()
                            work {
                                ShopApi(base, token, lang).post("/api/me/family/join", JSONObject().put("code", code))
                                activity.runOnUiThread { notice = t("family_joined"); familyCode = ""; refresh() }
                            }
                        }) { Text(t("family_join")) }
                        Text(t("stars_hint"), color = Color(0xFFA4AFD0))
                    }
                    "status" -> {
                        val level = serviceStatus.optString("status", "unknown")
                        Text(t("status_" + (if (level in setOf("ok", "degraded", "down")) level else "unknown")), style = MaterialTheme.typography.titleMedium,
                            color = when (level) { "ok" -> Color(0xFF2BD47D); "degraded" -> Color(0xFFFFB020); "down" -> Color(0xFFFF5A6E); else -> Color(0xFFA4AFD0) })
                        val srv = serviceStatus.optJSONObject("servers") ?: JSONObject()
                        Text("${t("status_servers")}: ${srv.optInt("online")} / ${srv.optInt("total")}")
                        val countries = serviceStatus.optJSONArray("countries") ?: JSONArray()
                        for (index in 0 until countries.length()) {
                            val c = countries.getJSONObject(index)
                            Text("${c.optString("country")} · ${c.optInt("online")} / ${c.optInt("total")}")
                        }
                        val components = serviceStatus.optJSONArray("components") ?: JSONArray()
                        for (index in 0 until components.length()) {
                            val c = components.getJSONObject(index)
                            Text("${c.optString("name")} · ${c.optString("status")}${if (c.optString("message").isNotBlank()) " · " + c.optString("message") else ""}")
                        }
                        Text(t("status_incidents"), style = MaterialTheme.typography.titleSmall)
                        val incidents = serviceStatus.optJSONArray("incidents") ?: JSONArray()
                        if (incidents.length() == 0) Text(t("status_none"))
                        for (index in 0 until incidents.length()) {
                            val i = incidents.getJSONObject(index)
                            Text("${i.optString("title")} · ${i.optString("since")}", color = Color(0xFFFFB020))
                        }
                    }
                    "support" -> {
                        OutlinedTextField(subject, { subject = it }, label = { Text(t("subject")) }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(message, { message = it }, label = { Text(t("message")) }, modifier = Modifier.fillMaxWidth())
                        Button(onClick = {
                            if (subject.isBlank() || message.isBlank()) return@Button
                            work {
                                ShopApi(base, token, lang).post("/api/me/support/tickets", JSONObject().put("subject", subject.trim()).put("message", message.trim()))
                                activity.runOnUiThread { notice = t("ticket_sent"); subject = ""; message = "" }
                            }
                        }) { Text(t("send")) }
                    }
                }
            }
        }
    }
}

private fun loadAuthedPng(base: String, path: String, token: String, lang: String): ImageBitmap? {

    val connection = (URL(base + path).openConnection() as HttpURLConnection).apply {
        instanceFollowRedirects = false
        connectTimeout = 15000
        readTimeout = 15000
        setRequestProperty("Accept", "image/png")
        setRequestProperty("Accept-Language", lang)
        setRequestProperty("User-Agent", "CorgiLusi-Android-User/2.15.0")
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
