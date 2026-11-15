package shop.remnawave.admin

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.util.UUID

/** One saved shop/admin connection. The session token lives in its own encrypted slot. */
data class AdminProfile(val id: String, val label: String, val base: String, val email: String) {
    val host: String get() = try { URI(base).host ?: base } catch (_: Exception) { base }
    val title: String get() = label.ifBlank { host }
}

/** HTTP failure with its status, so the UI can tell an expired session from a forbidden section. */
class ApiException(val status: Int, message: String) : IllegalStateException(message)

/**
 * Several admin profiles (different shops, or different accounts on one shop) on one device.
 * Each profile has a separate Keystore-encrypted session slot; switching never mixes data
 * because the UI clears everything loaded for the previous profile. The pre-multiprofile
 * single session becomes the "default" profile on upgrade, without signing out.
 */
class ProfileStore(private val prefs: SharedPreferences) {
    companion object {
        const val MAX_PROFILES = 8
        const val DEFAULT_ID = "default"
    }

    private fun slot(id: String) = if (id == DEFAULT_ID) "" else ".$id"

    fun tokens(id: String) = SecureTokenStore(prefs, slot(id))

    fun all(): List<AdminProfile> {
        val raw = prefs.getString("profiles", null)
        if (raw == null) {
            val legacy = prefs.getString("base", "") ?: ""
            return if (legacy.isBlank()) emptyList() else listOf(AdminProfile(DEFAULT_ID, "", legacy, "")).also { save(it) }
        }
        return try {
            val rows = JSONArray(raw)
            (0 until rows.length()).mapNotNull { index ->
                val row = rows.optJSONObject(index) ?: return@mapNotNull null
                val id = row.optString("id")
                if (id.isBlank()) null else AdminProfile(id, row.optString("label"), row.optString("base"), row.optString("email"))
            }
        } catch (_: Exception) { emptyList() }
    }

    private fun save(list: List<AdminProfile>) {
        val rows = JSONArray()
        list.forEach { rows.put(JSONObject().put("id", it.id).put("label", it.label).put("base", it.base).put("email", it.email)) }
        prefs.edit().putString("profiles", rows.toString()).apply()
    }

    fun find(id: String): AdminProfile? = all().firstOrNull { it.id == id }

    fun activeId(): String = prefs.getString("active_profile", null)?.takeIf { id -> all().any { it.id == id } } ?: all().firstOrNull()?.id ?: DEFAULT_ID

    fun setActive(id: String) { prefs.edit().putString("active_profile", id).apply() }

    fun newId(): String = UUID.randomUUID().toString().replace("-", "").take(12)

    fun duplicateOf(id: String, base: String, email: String): AdminProfile? =
        all().firstOrNull { it.id != id && it.base == base && it.email.equals(email, ignoreCase = true) }

    fun upsert(profile: AdminProfile) {
        val list = all().filter { it.id != profile.id } + profile
        save(list)
    }

    fun remove(id: String) {
        tokens(id).clear()
        prefs.edit().remove("base" + slot(id)).apply()
        save(all().filter { it.id != id })
        if (prefs.getString("active_profile", null) == id) prefs.edit().remove("active_profile").apply()
    }
}
