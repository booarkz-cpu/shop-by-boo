package shop.remnawave.admin

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.fragment.app.FragmentActivity
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.background
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
        // Screenshot mode for CI: debuggable builds only, started with --ez corgi_demo true --es corgi_tab <tab>.
        val demo = (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0 && intent?.getBooleanExtra("corgi_demo", false) == true
        if (!demo) window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        val demoTab = if (demo) intent?.getStringExtra("corgi_tab") ?: "overview" else "overview"
        setContent { MaterialTheme(colorScheme = remnaColors()) { AdminApp(demo, demoTab) } }
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
    fun put(path: String, body: JSONObject): Any = call("PUT", path, body)

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
            setRequestProperty("User-Agent", "CorgiLusi-Android-Admin/3.2.0")
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
private fun AdminApp(demo: Boolean = false, demoTab: String = "overview") {
    val context = LocalContext.current
    val activity = context as FragmentActivity
    val prefs = remember { context.getSharedPreferences("shop_admin", 0) }
    val profileStore = remember { ProfileStore(prefs) }
    var profiles by remember { mutableStateOf(profileStore.all()) }
    var activeId by remember { mutableStateOf(profileStore.activeId()) }
    val tokenStore = remember(activeId) { profileStore.tokens(activeId) }
    var lang by remember { mutableStateOf(prefs.getString("lang", "ru") ?: "ru") }
    var base by remember { mutableStateOf(profileStore.find(activeId)?.base ?: "") }
    var token by remember { mutableStateOf(if (demo) "demo" else tokenStore.read()) }
    var profileLabel by remember { mutableStateOf(profileStore.find(activeId)?.label ?: "") }
    var showProfiles by remember { mutableStateOf(false) }
    var signedInIds by remember { mutableStateOf(setOf<String>()) }
    var unlocked by remember { mutableStateOf(demo || token.isBlank()) }
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
    var tab by remember { mutableStateOf(demoTab) }
    var notice by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var overview by remember { mutableStateOf(JSONObject()) }
    var plans by remember { mutableStateOf(JSONArray()) }
    var payments by remember { mutableStateOf(JSONArray()) }
    var monitoring by remember { mutableStateOf(JSONObject()) }
    var platform by remember { mutableStateOf(JSONObject()) }
    var ops by remember { mutableStateOf(JSONObject()) }
    var nodeHealth by remember { mutableStateOf(JSONObject()) }
    var cashQueue by remember { mutableStateOf(JSONArray()) }
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
        platform = JSONObject(); ops = JSONObject(); nodeHealth = JSONObject(); cashQueue = JSONArray(); readiness = JSONObject(); alerts = JSONObject(); tickets = JSONArray(); broadcasts = JSONArray()
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
            // Node health appeared in v28.35: older shops simply show no node card.
            val nextNodeHealth = try { api.get("/api/admin/nodes/health") as JSONObject } catch (_: Exception) { JSONObject() }
            val nextCash = try { api.get("/api/admin/v41/providers") as JSONArray } catch (_: Exception) { JSONArray() }
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
                nodeHealth = nextNodeHealth
                cashQueue = nextCash
                readiness = nextReadiness
                alerts = nextAlerts
                tickets = nextTickets
                broadcasts = nextBroadcasts
                logo = nextLogo
            }
        }
    }
    LaunchedEffect(Unit) {
        if (!demo) return@LaunchedEffect
        // Fixed demo data for screenshots; nothing is requested from a server.
        base = "https://api.corgi-lusi.example"; profileLabel = "Корги Люси"
        overview = JSONObject("""{"role":"admin","plans":4,"payments":1284,"users":5320,"active_subscriptions":2871,"revenue_today":"48 300","revenue_month":"1 214 900"}""")
        plans = JSONArray("""[{"id":1,"name":"1 месяц","price":"299.00","enabled":true},{"id":2,"name":"3 месяца","price":"549.00","enabled":true},{"id":3,"name":"12 месяцев","price":"1499.00","enabled":true},{"id":4,"name":"Семейный","price":"2490.00","enabled":false}]""")
        payments = JSONArray("""[{"id":1284,"amount":"1499.00","currency":"RUB","status":"fulfilled","provider":"yookassa"},{"id":1283,"amount":"299.00","currency":"RUB","status":"paid","provider":"platega"},{"id":1282,"amount":"549.00","currency":"RUB","status":"pending","provider":"rollypay"},{"id":1281,"amount":"299.00","currency":"RUB","status":"refunded","provider":"yookassa"}]""")
        monitoring = JSONObject("""{"nodes":[{"name":"Амстердам","country":"NL","status":"online","users_online":412},{"name":"Франкфурт","country":"DE","status":"online","users_online":388},{"name":"Хельсинки","country":"FI","status":"online","users_online":201},{"name":"Стамбул","country":"TR","status":"offline","users_online":0}]}""")
        platform = JSONObject("""{"violations":[{"id":17,"score":82,"recommendation":"Торрент-трафик: ограничить"}],"agents":[{"name":"nl-1","cpu":"23%","last_seen_at":"2026-10-26T20:00:00"},{"name":"de-1","cpu":"41%","last_seen_at":"2026-10-26T20:00:00"}],"countries":[{"country":"RU","count":4210},{"country":"KZ","count":512},{"country":"BY","count":318}]}""")
        ops = JSONObject("""{"critical":0,"stale_agents":1,"agents":[{"name":"nl-1","cpu":"23%","mem":"41%"},{"name":"de-1","cpu":"41%","mem":"55%"}]}""")
        cashQueue = JSONArray("""[{"provider":"yookassa","enabled":true,"configured":true,"cooling":true,"success_count":1284,"failure_count":3},{"provider":"rollypay","enabled":true,"configured":true,"cooling":false,"success_count":212,"failure_count":0},{"provider":"freekassa","enabled":true,"configured":false,"cooling":false,"success_count":0,"failure_count":0}]""")
        nodeHealth = JSONObject("""{"nodes":[{"uuid":"n1","name":"Нидерланды","status":"online","users_online":184,"down_minutes":0},{"uuid":"n2","name":"Германия","status":"offline","users_online":0,"down_minutes":4}]}""")
        readiness = JSONObject("""{"ready":false,"checks":[{"title":"Платёжная система подключена","ok":true,"level":"required"},{"title":"Remnawave отвечает","ok":true,"level":"required"},{"title":"Резервные копии по расписанию","ok":true,"level":"required"},{"title":"Чеки в налоговую","ok":false,"level":"recommended","hint":"Тарифы и оплата → Чеки в налоговую"}]}""")
        alerts = JSONObject("""{"recipients":{"telegram":true,"email":false},"problems":[]}""")
        tickets = JSONArray("""[{"id":311,"subject":"Не подключается на iPhone","status":"open","message":"После обновления iOS Happ не видит подписку."},{"id":310,"subject":"Чек об оплате","status":"answered","message":"Пришлите, пожалуйста, чек за октябрь."}]""")
        broadcasts = JSONArray("""[{"id":42,"target":"active","status":"sent","sent_count":2871,"failed_count":3}]""")
    }
    LaunchedEffect(token) {
        if (demo) return@LaunchedEffect
        if (token.isNotBlank() && !unlocked) promptUnlock(activity, t("unlock")) { unlocked = it }
    }
    LaunchedEffect(token, lang, unlocked) {
        if (demo) return@LaunchedEffect
        if (token.isNotBlank() && unlocked) refresh()
    }
    LaunchedEffect(base) {
        if (demo) return@LaunchedEffect
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
    fun money(value: Any?) = value?.toString()?.removeSuffix(".00").orEmpty()
    val navItems = listOf("overview", "launch", "plans", "payments", "monitoring", "platform", "ops", "support", "broadcast", "panel")
    Box(Modifier.fillMaxSize().background(Remna.bg)) {
        Column(Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            RemnaHeader(t("app_name"), if (token.isNotBlank() && unlocked) profileTitle() else t("tagline"), logo, if (lang == "ru") "EN" else "RU") {
                lang = if (lang == "ru") "en" else "ru"
                prefs.edit().putString("lang", lang).apply()
            }
            if (notice.isNotBlank()) RemnaNotice(notice)
            if ((token.isBlank() || unlocked) && !demo) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    RemnaDot(if (token.isNotBlank()) Tone.OK else Tone.MUTED)
                    Spacer(Modifier.width(8.dp))
                    Text(if (base.isBlank()) t("add_profile") else profileTitle(), color = Remna.primaryInk, modifier = Modifier.weight(1f))
                    RemnaGhost("${t("profiles")} (${profiles.size})") { reloadProfiles(); showProfiles = !showProfiles }
                }
            }
            if (showProfiles && (token.isBlank() || unlocked)) RemnaCard(t("profiles")) {
                for (profile in profiles) {
                    val current = profile.id == activeId
                    val signed = profile.id in signedInIds
                    RemnaRow("${profile.title}${if (current) " · ${t("active_profile")}" else ""}",
                        "${profile.host}${if (profile.email.isNotBlank()) " · ${profile.email}" else ""}",
                        if (signed) t("signed_in") else t("signed_out"), if (signed) Tone.OK else Tone.MUTED) {
                        if (!current) RemnaGhost(t("switch_profile"), enabled = !busy) { switchTo(profile.id) }
                        RemnaGhost(t("remove_profile"), enabled = !busy, danger = true) {
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
                        }
                    }
                }
                RemnaPrimary(t("add_profile"), enabled = !busy) { addProfile() }
            }
            if (token.isBlank()) {
                RemnaCard(t("sign_in"), t("tagline")) {
                    RemnaField(profileLabel, { profileLabel = it.take(40) }, t("profile_label"))
                    RemnaField(base, { base = it }, t("server"))
                    RemnaField(email, { email = it }, t("email"))
                    RemnaField(password, { password = it }, t("password"), secret = true)
                    RemnaField(otp, { otp = it }, t("otp"))
                    RemnaPrimary(t("sign_in"), enabled = !busy) {
                        val normalized = try { normalizeBase(base) } catch (_: Exception) { notice = t("https_required"); return@RemnaPrimary }
                        if (!email.contains("@") || !email.contains(".")) { notice = t("email_invalid"); return@RemnaPrimary }
                        if (password.length < 8) { notice = t("password_short"); return@RemnaPrimary }
                        val profileId = activeId
                        val duplicate = profileStore.duplicateOf(profileId, normalized, email.trim())
                        if (duplicate != null) { notice = t("profile_duplicate"); reloadProfiles(); showProfiles = true; return@RemnaPrimary }
                        if (profileStore.find(profileId) == null && profileStore.all().size >= ProfileStore.MAX_PROFILES) { notice = t("profile_limit"); return@RemnaPrimary }
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
                    }
                }
            } else if (!unlocked) {
                RemnaCard(t("unlock")) {
                    RemnaPrimary(t("unlock")) { promptUnlock(activity, t("unlock")) { unlocked = it } }
                    RemnaGhost(t("sign_out"), danger = true) { signOut() }
                }
            } else {
                RemnaNav(navItems.map { it to t(it) }, tab) { tab = it }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    RemnaGhost(t("refresh"), enabled = !busy && !demo) { refresh() }
                    RemnaGhost(t("sign_out"), danger = true) { signOut() }
                }
                when (tab) {
                    "overview" -> {
                        RemnaKpiRow(t("plans") to overview.optInt("plans").toString(), t("payments") to overview.optInt("payments").toString())
                        if (overview.has("users")) RemnaKpiRow("Клиенты" to overview.optString("users"), "Активные подписки" to overview.optString("active_subscriptions"))
                        if (overview.has("revenue_today")) RemnaKpiRow("Выручка сегодня, ₽" to overview.optString("revenue_today"), "За месяц, ₽" to overview.optString("revenue_month"))
                        RemnaCard(t("role")) { RemnaRow(overview.optString("role").ifBlank { "—" }, profileTitle(), t("online"), Tone.OK) }
                    }
                    "plans" -> RemnaCard(t("plans")) {
                        if (plans.length() == 0) RemnaEmpty(t("no_data"))
                        for (index in 0 until plans.length()) {
                            val plan = plans.getJSONObject(index)
                            val on = plan.optBoolean("enabled")
                            RemnaRow(plan.optString("name"), "${money(plan.opt("price"))} ₽", if (on) t("enabled") else t("disabled"), if (on) Tone.OK else Tone.MUTED) {
                                RemnaGhost(if (on) t("disable_plan") else t("enable_plan"), enabled = !demo) {
                                    work {
                                        ShopApi(base, token, lang).post("/api/admin/plans/${plan.optInt("id")}/enabled", JSONObject().put("enabled", !on))
                                        activity.runOnUiThread { notice = t("plan_saved") }
                                    }
                                }
                            }
                        }
                    }
                    "payments" -> { RemnaCard(t("cash_queue")) {
                        // The order of gateways: an order goes to the first enabled, configured one that is not cooling down.
                        if (cashQueue.length() == 0) RemnaEmpty(t("no_data"))
                        for (index in 0 until cashQueue.length()) {
                            val row = cashQueue.getJSONObject(index)
                            val name = row.optString("provider")
                            val enabled = row.optBoolean("enabled")
                            val state = if (!enabled) t("disabled") else if (row.optBoolean("cooling")) t("cash_cooling") else if (row.optBoolean("configured")) t("cash_ready") else t("cash_no_keys")
                            RemnaRow("${index + 1}. $name", "${row.optInt("success_count")} / ${row.optInt("failure_count")}", state,
                                if (enabled && row.optBoolean("configured") && !row.optBoolean("cooling")) Tone.OK else Tone.WARN) {
                                RemnaGhost(if (enabled) t("cash_off") else t("cash_on"), enabled = !busy && !demo) {
                                    work {
                                        ShopApi(base, token, lang).put("/api/admin/v41/providers/$name", JSONObject().put("enabled", !enabled).put("priority", (index + 1) * 10))
                                        activity.runOnUiThread { notice = t("cash_saved"); refresh() }
                                    }
                                }
                                if (index > 0) RemnaGhost(t("cash_up"), enabled = !busy && !demo) {
                                    work {
                                        val above = cashQueue.getJSONObject(index - 1)
                                        ShopApi(base, token, lang).put("/api/admin/v41/providers/$name", JSONObject().put("enabled", enabled).put("priority", index * 10))
                                        ShopApi(base, token, lang).put("/api/admin/v41/providers/${above.optString("provider")}", JSONObject().put("enabled", above.optBoolean("enabled")).put("priority", (index + 1) * 10))
                                        activity.runOnUiThread { notice = t("cash_saved"); refresh() }
                                    }
                                }
                                if (row.optBoolean("cooling")) RemnaPrimary(t("cash_reset"), enabled = !busy && !demo) {
                                    work {
                                        ShopApi(base, token, lang).post("/api/admin/v41/providers/$name/reset", JSONObject())
                                        activity.runOnUiThread { refresh() }
                                    }
                                }
                            }
                        }
                    }
                    RemnaCard(t("payments")) {
                        if (payments.length() == 0) RemnaEmpty(t("no_data"))
                        for (index in 0 until payments.length()) {
                            val payment = payments.getJSONObject(index)
                            RemnaRow("#${payment.optInt("id")} · ${money(payment.opt("amount"))} ${payment.optString("currency")}", payment.optString("provider"), payment.optString("status")) {
                                RemnaGhost(t("payment_detail"), enabled = !demo) {
                                    work {
                                        val detail = ShopApi(base, token, lang).get("/api/admin/payments/${payment.optInt("id")}") as JSONObject
                                        activity.runOnUiThread { paymentDetail = detail }
                                    }
                                }
                            }
                        }
                        if (paymentDetail.length() > 0) RemnaNotice("#${paymentDetail.optInt("id")} · ${paymentDetail.optString("order_id")} · ${paymentDetail.optString("purpose")} · ${paymentDetail.optString("fulfillment_status")}", Tone.INFO)
                    }
                    }
                    "monitoring" -> RemnaCard(t("monitoring")) {
                        if (monitoring.optString("error").isNotBlank()) RemnaNotice(t("panel_down"), Tone.BAD)
                        val nodes = monitoring.optJSONArray("nodes") ?: JSONArray()
                        if (nodes.length() == 0) RemnaEmpty(t("no_data"))
                        for (index in 0 until nodes.length()) {
                            val node = publicNode(nodes.getJSONObject(index))
                            RemnaRow(node.optString("name"), "${node.optString("country")} · ${node.optInt("users_online")} online", node.optString("status"))
                        }
                    }
                    "platform" -> {
                        RemnaCard(t("violations")) {
                            val violations = platform.optJSONArray("violations") ?: JSONArray()
                            if (violations.length() == 0) RemnaEmpty(t("no_data"))
                            for (index in 0 until violations.length()) {
                                val row = violations.getJSONObject(index)
                                val score = row.optInt("score")
                                RemnaRow("#${row.optInt("id")} · ${t("score")} $score", row.optString("recommendation"), "$score", if (score >= 70) Tone.BAD else Tone.WARN) {
                                    RemnaGhost(t("restrict"), enabled = !demo, danger = true) {
                                        work {
                                            ShopApi(base, token, lang).post("/api/admin/platform/violations/${row.optInt("id")}/review", JSONObject().put("action", "restrict"))
                                            activity.runOnUiThread { notice = t("restricted") }
                                        }
                                    }
                                    RemnaGhost(t("clear"), enabled = !demo) {
                                        work {
                                            ShopApi(base, token, lang).post("/api/admin/platform/violations/${row.optInt("id")}/review", JSONObject().put("action", "clear"))
                                            activity.runOnUiThread { notice = t("cleared") }
                                        }
                                    }
                                }
                            }
                        }
                        RemnaCard(t("agents")) {
                            val agents = platform.optJSONArray("agents") ?: JSONArray()
                            if (agents.length() == 0) RemnaEmpty(t("no_data"))
                            for (index in 0 until agents.length()) {
                                val agent = agents.getJSONObject(index)
                                val stale = agent.optBoolean("stale") || agent.optString("last_seen_at").isBlank()
                                RemnaRow(agent.optString("name"), "CPU ${agent.optString("cpu")}", if (stale) t("stale") else t("online"), if (stale) Tone.WARN else Tone.OK)
                            }
                        }
                        RemnaCard(t("countries")) {
                            val countries = platform.optJSONArray("countries") ?: JSONArray()
                            for (index in 0 until countries.length()) {
                                val country = countries.getJSONObject(index)
                                RemnaRow(country.optString("country"), "", country.optInt("count").toString(), Tone.INFO)
                            }
                        }
                    }
                    "broadcast" -> {
                        RemnaCard(t("broadcast"), t("broadcast_hint")) {
                            RemnaNav(listOf("all" to t("all_telegram"), "active" to t("active_subs"), "inactive" to t("inactive_subs")), broadcastTarget) { broadcastTarget = it }
                            RemnaField(broadcastText, { broadcastText = it }, t("broadcast_text"), singleLine = false)
                            RemnaPrimary(t("queue_broadcast"), enabled = !busy && !demo) {
                                if (broadcastText.isBlank()) return@RemnaPrimary
                                work {
                                    ShopApi(base, token, lang).post("/api/admin/broadcasts", JSONObject().put("text", broadcastText.trim()).put("target", broadcastTarget))
                                    activity.runOnUiThread { notice = t("broadcast_queued"); broadcastText = "" }
                                }
                            }
                        }
                        RemnaCard(t("sent")) {
                            if (broadcasts.length() == 0) RemnaEmpty(t("no_data"))
                            for (index in 0 until broadcasts.length()) {
                                val row = broadcasts.getJSONObject(index)
                                val audience = when (row.optString("target")) {
                                    "active" -> t("active_subs")
                                    "inactive" -> t("inactive_subs")
                                    else -> t("all_telegram")
                                }
                                val status = row.optString("status")
                                RemnaRow("#${row.optInt("id")} · $audience", "${t("sent")} ${row.optInt("sent_count")} · ${t("failed")} ${row.optInt("failed_count")}", status) {
                                    if (status == "sending" || status == "failed") RemnaGhost(t("retry_broadcast")) {
                                        work {
                                            ShopApi(base, token, lang).post("/api/admin/broadcasts/${row.optInt("id")}/retry", JSONObject())
                                            activity.runOnUiThread { notice = t("broadcast_retried") }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    "launch" -> {
                        RemnaCard(t("launch")) {
                            if (readiness.length() == 0) RemnaEmpty(t("no_data"))
                            else {
                                RemnaNotice(if (readiness.optBoolean("ready")) t("launch_ready") else t("launch_missing"), if (readiness.optBoolean("ready")) Tone.OK else Tone.WARN)
                                val checks = readiness.optJSONArray("checks") ?: JSONArray()
                                for (index in 0 until checks.length()) {
                                    val c = checks.getJSONObject(index)
                                    val ok = c.optBoolean("ok")
                                    val required = c.optString("level") == "required"
                                    RemnaRow(c.optString("title"), if (!ok) c.optString("hint") else "", if (ok) "✓" else if (required) "✗" else t("recommended"),
                                        if (ok) Tone.OK else if (required) Tone.BAD else Tone.WARN)
                                }
                            }
                        }
                        RemnaCard(t("alerts")) {
                            val recipients = alerts.optJSONObject("recipients") ?: JSONObject()
                            RemnaRow(t("alerts_telegram"), "", if (recipients.optBoolean("telegram")) t("configured") else t("not_configured"), if (recipients.optBoolean("telegram")) Tone.OK else Tone.MUTED)
                            RemnaRow(t("alerts_email"), "", if (recipients.optBoolean("email")) t("configured") else t("not_configured"), if (recipients.optBoolean("email")) Tone.OK else Tone.MUTED)
                            RemnaPrimary(t("alerts_test"), enabled = !busy && !demo && (recipients.optBoolean("telegram") || recipients.optBoolean("email"))) {
                                work {
                                    ShopApi(base, token, lang).post("/api/admin/ops/alerts/test", JSONObject())
                                    activity.runOnUiThread { notice = t("alerts_sent") }
                                }
                            }
                            Text(t("problems_now"), color = Remna.textStrong)
                            val problems = alerts.optJSONArray("problems") ?: JSONArray()
                            if (problems.length() == 0) RemnaEmpty(t("no_problems"))
                            for (index in 0 until problems.length()) {
                                val pr = problems.getJSONObject(index)
                                RemnaRow(pr.optString("title"), pr.optString("detail"), "!", Tone.WARN)
                            }
                        }
                    }
                    "ops" -> {
                        RemnaKpiRow(t("critical") to ops.optInt("critical").toString(), t("stale_agents") to ops.optInt("stale_agents").toString())
                        RemnaCard(t("ops")) {
                            val agents = ops.optJSONArray("agents") ?: JSONArray()
                            if (agents.length() == 0) RemnaEmpty(t("no_data"))
                            for (index in 0 until agents.length()) {
                                val agent = agents.getJSONObject(index)
                                RemnaRow(agent.optString("name"), "CPU ${agent.optString("cpu")} · RAM ${agent.optString("mem")}", t("online"), Tone.OK)
                            }
                        }
                        RemnaCard(t("nodes")) {
                            val nodes = nodeHealth.optJSONArray("nodes") ?: JSONArray()
                            if (nodeHealth.optString("error").isNotBlank() && !nodeHealth.isNull("error")) RemnaNotice(nodeHealth.optString("error"), Tone.BAD)
                            if (nodes.length() == 0) RemnaEmpty(t("no_data"))
                            for (index in 0 until nodes.length()) {
                                val node = nodes.getJSONObject(index)
                                val online = node.optString("status") == "online"
                                val detail = if (online) "${node.optString("users_online")} online" else "${t("node_down")} ${node.optInt("down_minutes")} мин"
                                RemnaRow(node.optString("name"), detail, node.optString("status"), if (online) Tone.OK else Tone.BAD) {
                                    RemnaGhost(t("node_restart"), enabled = !busy && !demo) {
                                        work {
                                            ShopApi(base, token, lang).post("/api/admin/nodes/${node.optString("uuid")}/restart", JSONObject())
                                            activity.runOnUiThread { notice = t("node_restarted") }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    "support" -> RemnaCard(t("support")) {
                        RemnaField(reply, { reply = it }, t("reply"), singleLine = false)
                        if (tickets.length() == 0) RemnaEmpty(t("no_data"))
                        for (index in 0 until tickets.length()) {
                            val ticket = tickets.getJSONObject(index)
                            RemnaRow("#${ticket.optInt("id")} · ${ticket.optString("subject")}", ticket.optString("message"), ticket.optString("status")) {
                                RemnaGhost(t("ai_draft"), enabled = !busy && !demo) {
                                    work {
                                        val out = ShopApi(base, token, lang).post("/api/admin/support/tickets/${ticket.optInt("id")}/draft", JSONObject()) as JSONObject
                                        activity.runOnUiThread { reply = out.optString("draft") }
                                    }
                                }
                                RemnaPrimary(t("send"), enabled = !busy && !demo, modifier = Modifier) {
                                    if (reply.isBlank()) return@RemnaPrimary
                                    work {
                                        ShopApi(base, token, lang).post("/api/admin/support/tickets/${ticket.optInt("id")}/reply", JSONObject().put("reply", reply.trim()))
                                        activity.runOnUiThread { notice = t("reply_sent"); reply = "" }
                                    }
                                }
                            }
                        }
                    }
                    "panel" -> RemnaCard(t("panel")) {
                        // Everything the native tabs do not cover lives in the web panel; the ticket is single-use and lives 60 s.
                        Text(t("panel_hint"), color = Remna.text)
                        RemnaPrimary(t("panel_open"), enabled = !busy && !demo) {
                            work {
                                val out = ShopApi(base, token, lang).post("/api/admin/auth/web-ticket", JSONObject()) as JSONObject
                                val url = out.optString("url")
                                if (url.startsWith("https://")) activity.runOnUiThread {
                                    activity.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url)))
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

private fun loadStrings(context: android.content.Context, lang: String): JSONObject {
    val text = context.assets.open("l10n.json").bufferedReader().use { it.readText() }
    return JSONObject(text).getJSONObject(lang)
}
