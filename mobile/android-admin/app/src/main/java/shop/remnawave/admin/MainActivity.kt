package shop.remnawave.admin

import android.os.Bundle
import androidx.activity.compose.setContent
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.concurrent.Executors
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.concurrent.thread



/** Tokens are encrypted by a non-exportable Android Keystore AES-GCM key.
 * The API origin is authenticated as AAD. Legacy plaintext sessions are discarded.
 */
class SecureTokenStore(private val prefs: android.content.SharedPreferences, slot: String = "") {
    private val alias = "shop.session.v2"
    // Each admin profile has its own slot; the empty slot is the original single session.
    private val tokenKey = "secure_token$slot"
    private val baseKey = "base$slot"
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
    fun clear() { prefs.edit().remove("token").remove(tokenKey).commit() }
    fun read(): String {
        val encoded = prefs.getString(tokenKey, null) ?: return ""
        return try {
            val raw = android.util.Base64.decode(encoded, android.util.Base64.NO_WRAP)
            require(raw.size > 28)
            val cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(javax.crypto.Cipher.DECRYPT_MODE, key(), javax.crypto.spec.GCMParameterSpec(128, raw.copyOfRange(0, 12)))
            cipher.updateAAD((prefs.getString(baseKey, "") ?: "").toByteArray(Charsets.UTF_8))
            String(cipher.doFinal(raw.copyOfRange(12, raw.size)), Charsets.UTF_8)
        } catch (_: Exception) { clear(); "" }
    }
    fun write(token: String, base: String) {
        if (token.isBlank()) { clear(); return }
        val cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(javax.crypto.Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(base.toByteArray(Charsets.UTF_8))
        val encoded = android.util.Base64.encodeToString(cipher.iv + cipher.doFinal(token.toByteArray(Charsets.UTF_8)), android.util.Base64.NO_WRAP)
        check(prefs.edit().putString(baseKey, base).putString(tokenKey, encoded).remove("token").commit()) {
            "Could not securely store the session"
        }
    }
}

class MainActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        setContent { MaterialTheme(colorScheme = shopColors()) { AdminApp() } }
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
    fun get(path: String): Any = call("GET", path, null)
    fun post(path: String, body: JSONObject): Any = call("POST", path, body)

    private fun call(method: String, path: String, body: JSONObject?): Any {
        val verifier = if (path in setOf("/api/auth/login", "/api/auth/register", "/api/admin/auth/login")) pkceVerifier() else null
        val connection = (URL(base + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            instanceFollowRedirects = false
            connectTimeout = 15000
            readTimeout = 15000
            setRequestProperty("Accept", "application/json")
            if (verifier != null) setRequestProperty("X-Shop-Code-Challenge", pkceChallenge(verifier))
            setRequestProperty("Accept-Language", lang)
            setRequestProperty("User-Agent", "CorgiLusi-Android-Admin/3.1.0")
            // Historical compatibility marker: CorgiLusi-Android-Admin/2.10.0
            // Historical compatibility marker: CorgiLusi-Android-Admin/2.9.0
            setRequestProperty("X-Shop-Client", "android-admin")


            if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                outputStream.use { it.write(body.toString().toByteArray()) }
            }
        }
        val code = connection.responseCode
        val text = (if (code in 200..299) connection.inputStream else connection.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code !in 200..299) throw ApiException(code, detailOf(text, code))
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
private fun AdminApp() {
    val context = LocalContext.current
    val activity = context as FragmentActivity
    val prefs = remember { context.getSharedPreferences("shop_admin", 0) }
    val profileStore = remember { ProfileStore(prefs) }
    var profiles by remember { mutableStateOf(profileStore.all()) }
    var activeId by remember { mutableStateOf(profileStore.activeId()) }
    val tokenStore = remember(activeId) { profileStore.tokens(activeId) }
    var lang by remember { mutableStateOf(prefs.getString("lang", "ru") ?: "ru") }
    var base by remember { mutableStateOf(profileStore.find(activeId)?.base ?: "") }
    var token by remember { mutableStateOf(tokenStore.read()) }
    var profileLabel by remember { mutableStateOf(profileStore.find(activeId)?.label ?: "") }
    var showProfiles by remember { mutableStateOf(false) }
    var signedInIds by remember { mutableStateOf(setOf<String>()) }
    var unlocked by remember { mutableStateOf(token.isBlank()) }
    DisposableEffect(activity) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) unlocked = false
        }
        activity.lifecycle.addObserver(observer)
        onDispose { activity.lifecycle.removeObserver(observer) }
    }

    var paymentDetail by remember { mutableStateOf(JSONObject()) }
    var email by remember { mutableStateOf(profileStore.find(activeId)?.email ?: "") }
    var password by remember { mutableStateOf("") }
    var otp by remember { mutableStateOf("") }
    var tab by remember { mutableStateOf("overview") }
    var notice by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var overview by remember { mutableStateOf(JSONObject()) }
    var plans by remember { mutableStateOf(JSONArray()) }
    var payments by remember { mutableStateOf(JSONArray()) }
    var monitoring by remember { mutableStateOf(JSONObject()) }
    var platform by remember { mutableStateOf(JSONObject()) }
    var ops by remember { mutableStateOf(JSONObject()) }
    var readiness by remember { mutableStateOf(JSONObject()) }
    var alerts by remember { mutableStateOf(JSONObject()) }
    var tickets by remember { mutableStateOf(JSONArray()) }
    var broadcasts by remember { mutableStateOf(JSONArray()) }
    var broadcastText by remember { mutableStateOf("") }
    var broadcastTarget by remember { mutableStateOf("all") }
    var reply by remember { mutableStateOf("") }
    var logo by remember { mutableStateOf<ImageBitmap?>(null) }
    val strings = remember(lang) { loadStrings(context, lang) }
    fun t(key: String) = strings.optString(key, key)
    fun profileTitle(): String = profileStore.find(activeId)?.title ?: (try { URI(base).host } catch (_: Exception) { null } ?: base)
    fun clearLoaded() {
        overview = JSONObject(); plans = JSONArray(); payments = JSONArray(); monitoring = JSONObject()
        platform = JSONObject(); ops = JSONObject(); readiness = JSONObject(); alerts = JSONObject(); tickets = JSONArray(); broadcasts = JSONArray()
        paymentDetail = JSONObject(); logo = null; reply = ""; broadcastText = ""
    }
    fun reloadProfiles() {
        profiles = profileStore.all()
        signedInIds = profiles.filter { profileStore.tokens(it.id).read().isNotBlank() }.map { it.id }.toSet()
    }
    fun switchTo(id: String) {
        clearLoaded()
        profileStore.setActive(id)
        activeId = id
        val profile = profileStore.find(id)
        base = profile?.base ?: ""
        email = profile?.email ?: ""
        profileLabel = profile?.label ?: ""
        password = ""; otp = ""; tab = "overview"
        token = profileStore.tokens(id).read()
        showProfiles = false
        notice = if (profile != null) t("profile_switched").replace("{profile}", profile.title) else ""
    }
    fun addProfile() {
        if (profiles.size >= ProfileStore.MAX_PROFILES) { notice = t("profile_limit"); return }
        clearLoaded()
        activeId = profileStore.newId()
        base = ""; email = ""; password = ""; otp = ""; profileLabel = ""; token = ""
        showProfiles = false
        notice = ""
    }
    fun signOut() {
        val previous = token
        val origin = base
        tokenStore.clear()
        token = ""
        unlocked = false
        clearLoaded()
        thread {
            try {
                if (previous.isNotBlank()) ShopApi(origin, previous, lang).post("/api/admin/auth/logout", JSONObject())
            } catch (_: Exception) {
                activity.runOnUiThread { notice = "Signed out locally; server session revocation could not be confirmed." }
            }
        }
    }
    fun work(block: () -> Unit) {
        busy = true
        notice = ""
        val startedFor = activeId
        thread {
            var expired = false
            val error = try { block(); null } catch (exc: ApiException) {
                when (exc.status) {
                    401 -> { expired = true; t("session_expired").replace("{profile}", profileTitle()) }
                    403 -> exc.message?.takeIf { it.isNotBlank() && !it.startsWith("HTTP") } ?: t("forbidden")
                    else -> exc.message ?: "HTTP ${exc.status}"
                }
            } catch (exc: java.io.IOException) {
                "${t("network_error").replace("{profile}", profileTitle())} (${exc.javaClass.simpleName})"
            } catch (exc: Exception) { exc.message ?: "HTTP" }
            activity.runOnUiThread {
                busy = false
                if (expired && startedFor == activeId) {
                    // Keep the profile, drop only its dead session, so the admin can sign in again.
                    tokenStore.clear()
                    token = ""
                    clearLoaded()
                }
                if (error != null) notice = error
            }
        }
    }
    fun refresh() {
        val api = ShopApi(base, token, lang)
        val refreshedFor = activeId
        work {
            val nextOverview = api.get("/api/admin/overview") as JSONObject
            val nextPlans = api.get("/api/admin/plans") as JSONArray
            val nextPayments = api.get("/api/admin/payments") as JSONArray
            val nextMonitoring = api.get("/api/admin/remnawave/monitoring") as JSONObject
            val nextPlatform = api.get("/api/admin/platform/summary") as JSONObject
            val nextOps = api.get("/api/admin/mobile/ops") as JSONObject
            val nextTickets = api.get("/api/admin/support/tickets") as JSONArray
            // Shops before v28.27.0 have no launch checks: the other tabs keep working.
            val nextReadiness = try { api.get("/api/admin/ops/readiness") as JSONObject } catch (_: Exception) { JSONObject() }
            val nextAlerts = try { api.get("/api/admin/ops/alerts") as JSONObject } catch (_: Exception) { JSONObject() }
            val nextMarketing = api.get("/api/admin/marketing") as JSONObject
            val nextBroadcasts = nextMarketing.optJSONArray("broadcasts") ?: JSONArray()
            val nextLogo = try {
                val catalog = api.get("/api/admin/apps") as JSONObject
                loadLogoBitmap(base, catalog.optString("logo_url"))?.asImageBitmap()
            } catch (_: Exception) { null }
            activity.runOnUiThread {
                // A slow response must not paint the previous profile's data after a switch.
                if (refreshedFor != activeId) return@runOnUiThread
                overview = nextOverview
                plans = nextPlans
                payments = nextPayments
                monitoring = nextMonitoring
                platform = nextPlatform
                ops = nextOps
                readiness = nextReadiness
                alerts = nextAlerts
                tickets = nextTickets
                broadcasts = nextBroadcasts
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
                    lang = if (lang == "ru") "en" else "ru"
                    prefs.edit().putString("lang", lang).apply()
                }) { Text(if (lang == "ru") "EN" else "RU") }
            }
            Text(t("tagline"), color = Color(0xFFA4AFD0))
            if (token.isBlank() || unlocked) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(if (base.isBlank()) t("add_profile") else profileTitle(), color = Color(0xFF93C5FD))
                    TextButton(onClick = { reloadProfiles(); showProfiles = !showProfiles }) { Text("${t("profiles")} (${profiles.size})") }
                }
            }
            if (notice.isNotBlank()) Text(notice, color = Color(0xFFFFB020))
            if (showProfiles && (token.isBlank() || unlocked)) {
                for (profile in profiles) {
                    val current = profile.id == activeId
                    val state = if (profile.id in signedInIds) t("signed_in") else t("signed_out")
                    Text("${profile.title} · ${profile.host}${if (profile.email.isNotBlank()) " · ${profile.email}" else ""} · $state${if (current) " · ${t("active_profile")}" else ""}")
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        if (!current) TextButton(enabled = !busy, onClick = { switchTo(profile.id) }) { Text(t("switch_profile")) }
                        TextButton(enabled = !busy, onClick = {
                            val removed = profile
                            val removedToken = profileStore.tokens(removed.id).read()
                            profileStore.remove(removed.id)
                            thread {
                                try { if (removedToken.isNotBlank()) ShopApi(removed.base, removedToken, lang).post("/api/admin/auth/logout", JSONObject()) } catch (_: Exception) { }
                            }
                            reloadProfiles()
                            if (current) {
                                val next = profileStore.all().firstOrNull()
                                if (next != null) switchTo(next.id) else addProfile()
                            }
                            notice = t("profile_removed")
                        }) { Text(t("remove_profile")) }
                    }
                }
                Button(enabled = !busy, onClick = { addProfile() }) { Text(t("add_profile")) }
            }
            if (token.isBlank()) {
                OutlinedTextField(profileLabel, { profileLabel = it.take(40) }, label = { Text(t("profile_label")) }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(base, { base = it }, label = { Text(t("server")) }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(email, { email = it }, label = { Text(t("email")) }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(password, { password = it }, label = { Text(t("password")) }, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                OutlinedTextField(otp, { otp = it }, label = { Text(t("otp")) }, modifier = Modifier.fillMaxWidth())
                Button(onClick = {
                    val normalized = try { normalizeBase(base) } catch (_: Exception) { notice = t("https_required"); return@Button }
                    if (!email.contains("@") || !email.contains(".")) { notice = t("email_invalid"); return@Button }
                    if (password.length < 8) { notice = t("password_short"); return@Button }
                    val profileId = activeId
                    val duplicate = profileStore.duplicateOf(profileId, normalized, email.trim())
                    if (duplicate != null) { notice = t("profile_duplicate"); reloadProfiles(); showProfiles = true; return@Button }
                    if (profileStore.find(profileId) == null && profileStore.all().size >= ProfileStore.MAX_PROFILES) { notice = t("profile_limit"); return@Button }
                    val label = profileLabel.trim()
                    work {
                        val body = JSONObject().put("email", email.trim()).put("password", password)
                        if (otp.isNotBlank()) body.put("otp", otp.trim())
                        val response = ShopApi(normalized, "", lang).post("/api/admin/auth/login", body) as JSONObject
                        val issued = response.optString("access_token")
                        if (issued.isBlank()) throw IllegalStateException("HTTP")
                        profileStore.tokens(profileId).write(issued, normalized)
                        profileStore.upsert(AdminProfile(profileId, label, normalized, email.trim()))
                        profileStore.setActive(profileId)
                        activity.runOnUiThread {
                            reloadProfiles()
                            base = normalized
                            token = issued
                            password = ""
                            otp = ""
                            unlocked = activity.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
                            prefs.edit().putString("lang", lang).apply()
                            notice = "${t("role")}: ${response.optString("role")}"
                        }
                    }
                }, enabled = !busy) { Text(t("sign_in")) }
            } else if (!unlocked) {
                Button(onClick = { promptUnlock(activity, t("unlock")) { unlocked = it } }) { Text(t("unlock")) }
                TextButton(onClick = { signOut() }) { Text(t("sign_out")) }
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("overview", "launch", "plans", "payments", "monitoring", "platform", "ops", "support", "broadcast").forEach { key ->
                        FilterChip(selected = tab == key, onClick = { tab = key }, label = { Text(t(key)) })
                    }
                }
                TextButton(onClick = { refresh() }, enabled = !busy) { Text(t("refresh")) }
                TextButton(onClick = {
                    signOut()
                }) { Text(t("sign_out")) }
                when (tab) {
                    "overview" -> Text("${t("role")} ${overview.optString("role")} · ${t("plans")} ${overview.optInt("plans")} · ${t("payments")} ${overview.optInt("payments")}")
                    "plans" -> {
                        if (plans.length() == 0) Text(t("no_data"))
                        for (index in 0 until plans.length()) {
                            val plan = plans.getJSONObject(index)
                            Text("${plan.optString("name")} · ${plan.opt("price")} · ${if (plan.optBoolean("enabled")) t("enabled") else t("disabled")}")
                            TextButton(onClick = {
                                val enabled = !plan.optBoolean("enabled")
                                work {
                                    ShopApi(base, token, lang).post("/api/admin/plans/${plan.optInt("id")}/enabled", JSONObject().put("enabled", enabled))
                                    activity.runOnUiThread { notice = t("plan_saved") }
                                }
                            }) { Text(if (plan.optBoolean("enabled")) t("disable_plan") else t("enable_plan")) }
                        }
                    }
                    "payments" -> {
                        if (payments.length() == 0) Text(t("no_data"))
                        for (index in 0 until payments.length()) {
                            val payment = payments.getJSONObject(index)
                            Text("#${payment.optInt("id")} · ${payment.opt("amount")} ${payment.optString("currency")} · ${payment.optString("status")}")
                            TextButton(onClick = {
                                work {
                                    val detail = ShopApi(base, token, lang).get("/api/admin/payments/${payment.optInt("id")}") as JSONObject
                                    activity.runOnUiThread { paymentDetail = detail }
                                }
                            }) { Text(t("payment_detail")) }
                        }
                        if (paymentDetail.length() > 0) Text("#${paymentDetail.optInt("id")} · ${paymentDetail.optString("order_id")} · ${paymentDetail.optString("purpose")} · ${paymentDetail.optString("fulfillment_status")}")
                    }
                    "monitoring" -> {
                        if (monitoring.optString("error").isNotBlank()) Text(t("panel_down"))
                        val nodes = monitoring.optJSONArray("nodes") ?: JSONArray()
                        if (nodes.length() == 0) Text(t("no_data"))
                        for (index in 0 until nodes.length()) {
                            val node = publicNode(nodes.getJSONObject(index))
                            Text("${node.optString("name")} · ${node.optString("country")} · ${node.optString("status")} · ${node.optInt("users_online")}")
                        }
                    }
                    "platform" -> {
                        Text(t("violations"))
                        val violations = platform.optJSONArray("violations") ?: JSONArray()
                        if (violations.length() == 0) Text(t("no_data"))
                        for (index in 0 until violations.length()) {
                            val row = violations.getJSONObject(index)
                            Text("#${row.optInt("id")} · ${t("score")} ${row.optInt("score")} · ${row.optString("recommendation")}")
                            Row {
                                TextButton(onClick = {
                                    work {
                                        ShopApi(base, token, lang).post("/api/admin/platform/violations/${row.optInt("id")}/review", JSONObject().put("action", "restrict"))
                                        activity.runOnUiThread { notice = t("restricted") }
                                    }
                                }) { Text(t("restrict")) }
                                TextButton(onClick = {
                                    work {
                                        ShopApi(base, token, lang).post("/api/admin/platform/violations/${row.optInt("id")}/review", JSONObject().put("action", "clear"))
                                        activity.runOnUiThread { notice = t("cleared") }
                                    }
                                }) { Text(t("clear")) }
                            }
                        }
                        Text(t("agents"))
                        val agents = platform.optJSONArray("agents") ?: JSONArray()
                        for (index in 0 until agents.length()) {
                            val agent = agents.getJSONObject(index)
                            Text("${agent.optString("name")} · CPU ${agent.optString("cpu")} · ${if (agent.optBoolean("stale") || agent.optString("last_seen_at").isBlank()) t("stale") else t("online")}")
                        }
                        Text(t("countries"))
                        val countries = platform.optJSONArray("countries") ?: JSONArray()
                        for (index in 0 until countries.length()) {
                            val country = countries.getJSONObject(index)
                            Text("${country.optString("country")}: ${country.optInt("count")}")
                        }
                    }
                    "broadcast" -> {
                        Text(t("broadcast_hint"), color = Color(0xFFA4AFD0))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            listOf("all" to "all_telegram", "active" to "active_subs", "inactive" to "inactive_subs").forEach { (value, key) ->
                                FilterChip(selected = broadcastTarget == value, onClick = { broadcastTarget = value }, label = { Text(t(key)) })
                            }
                        }
                        OutlinedTextField(broadcastText, { broadcastText = it }, label = { Text(t("broadcast_text")) }, modifier = Modifier.fillMaxWidth())
                        Button(onClick = {
                            if (broadcastText.isBlank()) return@Button
                            work {
                                ShopApi(base, token, lang).post("/api/admin/broadcasts", JSONObject().put("text", broadcastText.trim()).put("target", broadcastTarget))
                                activity.runOnUiThread { notice = t("broadcast_queued"); broadcastText = "" }
                            }
                        }, enabled = !busy) { Text(t("queue_broadcast")) }
                        if (broadcasts.length() == 0) Text(t("no_data"))
                        for (index in 0 until broadcasts.length()) {
                            val row = broadcasts.getJSONObject(index)
                            val audience = when (row.optString("target")) {
                                "active" -> t("active_subs")
                                "inactive" -> t("inactive_subs")
                                else -> t("all_telegram")
                            }
                            Text("#${row.optInt("id")} · $audience · ${row.optString("status")} · ${t("sent")} ${row.optInt("sent_count")} · ${t("failed")} ${row.optInt("failed_count")}")
                            val status = row.optString("status")
                            if (status == "sending" || status == "failed") {
                                TextButton(onClick = {
                                    work {
                                        ShopApi(base, token, lang).post("/api/admin/broadcasts/${row.optInt("id")}/retry", JSONObject())
                                        activity.runOnUiThread { notice = t("broadcast_retried") }
                                    }
                                }) { Text(t("retry_broadcast")) }
                            }
                        }
                    }
                    "launch" -> {
                        if (readiness.length() == 0) Text(t("no_data"))
                        else {
                            Text(if (readiness.optBoolean("ready")) t("launch_ready") else t("launch_missing"), style = MaterialTheme.typography.titleMedium,
                                color = if (readiness.optBoolean("ready")) Color(0xFF2BD47D) else Color(0xFFFFB020))
                            val checks = readiness.optJSONArray("checks") ?: JSONArray()
                            for (index in 0 until checks.length()) {
                                val c = checks.getJSONObject(index)
                                val mark = if (c.optBoolean("ok")) "✓" else if (c.optString("level") == "required") "✗" else "!"
                                Text("$mark ${c.optString("title")}${if (c.optString("level") != "required") " · " + t("recommended") else ""}")
                                if (!c.optBoolean("ok") && c.optString("hint").isNotBlank()) Text(c.optString("hint"), color = Color(0xFFA4AFD0))
                            }
                        }
                        Text(t("alerts"), style = MaterialTheme.typography.titleMedium)
                        val recipients = alerts.optJSONObject("recipients") ?: JSONObject()
                        Text("${t("alerts_telegram")}: ${if (recipients.optBoolean("telegram")) t("configured") else t("not_configured")} · ${t("alerts_email")}: ${if (recipients.optBoolean("email")) t("configured") else t("not_configured")}")
                        Button(enabled = !busy && (recipients.optBoolean("telegram") || recipients.optBoolean("email")), onClick = {
                            work {
                                ShopApi(base, token, lang).post("/api/admin/ops/alerts/test", JSONObject())
                                activity.runOnUiThread { notice = t("alerts_sent") }
                            }
                        }) { Text(t("alerts_test")) }
                        Text(t("problems_now"), style = MaterialTheme.typography.titleSmall)
                        val problems = alerts.optJSONArray("problems") ?: JSONArray()
                        if (problems.length() == 0) Text(t("no_problems"))
                        for (index in 0 until problems.length()) {
                            val pr = problems.getJSONObject(index)
                            Text(pr.optString("title"), color = Color(0xFFFFB020))
                            Text(pr.optString("detail"), color = Color(0xFFA4AFD0))
                        }
                    }
                    "ops" -> {
                        Text(t("ops"))
                        Text("${t("critical")}: ${ops.optInt("critical")}")
                        Text("${t("stale_agents")}: ${ops.optInt("stale_agents")}")
                        val agents = ops.optJSONArray("agents") ?: JSONArray()
                        for (index in 0 until agents.length()) {
                            val agent = agents.getJSONObject(index)
                            Text("${agent.optString("name")} · CPU ${agent.optString("cpu")} · RAM ${agent.optString("mem")}")
                        }
                    }
                    "support" -> {
                        OutlinedTextField(reply, { reply = it }, label = { Text(t("reply")) }, modifier = Modifier.fillMaxWidth())
                        if (tickets.length() == 0) Text(t("no_data"))
                        for (index in 0 until tickets.length()) {
                            val ticket = tickets.getJSONObject(index)
                            Text("#${ticket.optInt("id")} · ${ticket.optString("subject")} · ${ticket.optString("status")}")
                            Text(ticket.optString("message"))
                            Button(onClick = {
                                if (reply.isBlank()) return@Button
                                work {
                                    ShopApi(base, token, lang).post("/api/admin/support/tickets/${ticket.optInt("id")}/reply", JSONObject().put("reply", reply.trim()))
                                    activity.runOnUiThread { notice = t("reply_sent"); reply = "" }
                                }
                            }) { Text(t("send")) }
                        }
                    }
                }
            }
        }
    }
}

private fun loadStrings(context: android.content.Context, lang: String): JSONObject {
    val text = context.assets.open("l10n.json").bufferedReader().use { it.readText() }
    return JSONObject(text).getJSONObject(lang)
}
