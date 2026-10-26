package shop.remnawave.user.ui

import androidx.compose.ui.graphics.ImageBitmap
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/** Everything the screens show, loaded by MainActivity from the shop API. */
data class ShopData(
    val dashboard: JSONObject = JSONObject(),
    val profiles: JSONArray = JSONArray(),
    val plans: JSONArray = JSONArray(),
    val servers: JSONObject = JSONObject(),
    val connection: JSONObject = JSONObject(),
    val traffic: JSONObject = JSONObject(),
    val devices: JSONArray = JSONArray(),
    val notifications: JSONArray = JSONArray(),
    val routing: JSONObject = JSONObject(),
    val family: JSONObject = JSONObject(),
    val status: JSONObject = JSONObject(),
    val passkeys: JSONArray = JSONArray(),
    val config: JSONObject = JSONObject(),
    val qr: ImageBitmap? = null,
) {
    val user: JSONObject get() = dashboard.optJSONObject("user") ?: JSONObject()
    val subscription: JSONObject? get() = dashboard.optJSONObject("subscription")

    val subscribed: Boolean
        get() {
            val sub = subscription ?: return false
            if (sub.optString("status") in setOf("expired", "cancelled")) return false
            val days = daysLeft()
            return days == null || days >= 0
        }

    val subscriptionUrl: String
        get() = connection.optString("subscription_url").ifBlank { subscription?.optString("subscription_url").orEmpty() }
            .takeIf { it.startsWith("https://") }.orEmpty()

    val customerId: String
        get() = user.optString("referral_code").ifBlank { user.optInt("id").takeIf { it > 0 }?.toString().orEmpty() }

    fun expiresDate(): String = subscription?.optString("expires_at").orEmpty().take(10)

    fun daysLeft(): Long? = try {
        ChronoUnit.DAYS.between(LocalDate.now(), LocalDate.parse(expiresDate()))
    } catch (_: Exception) {
        null
    }

    /** Matching plan of the active subscription (devices and traffic limits). */
    fun currentPlan(): JSONObject? {
        val planId = subscription?.optInt("plan_id") ?: return null
        for (i in 0 until plans.length()) plans.optJSONObject(i)?.takeIf { it.optInt("id") == planId }?.let { return it }
        return null
    }

    fun activeDevices(): Int = (0 until devices.length()).count { devices.optJSONObject(it)?.optString("status") == "active" }

    fun nodes(): List<JSONObject> {
        val rows = servers.optJSONArray("nodes") ?: return emptyList()
        return (0 until rows.length()).mapNotNull { rows.optJSONObject(it) }
    }
}

/** Switches and transient state of the interface. */
data class UiFlags(
    val vpn: VpnState = VpnState.OFF,
    val busy: Boolean = false,
    val notice: String = "",
    val offline: Boolean = false,
    val pushEnabled: Boolean = false,
    val widgetEnabled: Boolean = false,
    val selectedPlan: Int = 0,
    val languageLabel: String = "RU",
    val version: String = "",
    val topupAmount: String = "300",
)

/** What the screens can ask the activity to do. */
interface ShopActions {
    fun run(button: LayoutButton)
    fun open(sectionId: String)
    fun link(url: String)
    fun selectPlan(planId: Int)
    fun selectSubscription(subscriptionId: Int)
    fun revokeDevice(deviceId: Int)
    fun markRead(notificationId: Int)
    fun removeFamilyMember(memberId: Int)
    fun joinFamily(code: String)
    fun deletePasskey(passkeyId: Int)
    fun setTopupAmount(amount: String)
}

fun formatBytes(bytes: Long): String {
    val gb = bytes / 1_000_000_000.0
    return if (gb >= 10) "%.0f GB".format(gb) else "%.1f GB".format(gb)
}

/** Monthly price of a plan for the «… ₽/мес» line and the discount badge against the shortest plan. */
fun monthlyPrice(plan: JSONObject): Double {
    val price = plan.optString("final_price").ifBlank { plan.optString("price") }.toDoubleOrNull() ?: 0.0
    val days = plan.optInt("duration_days", 30).coerceAtLeast(1)
    return price * 30.0 / days
}
