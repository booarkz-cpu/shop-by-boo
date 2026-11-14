package shop.corgi.client.core

import org.json.JSONObject

/**
 * v1.8.1 (N12, phase 3): «Geek Mode» — the raw Xray JSON the tunnel starts with, edited by hand. The generated config
 * is the starting point; while Geek Mode is on, the edited text replaces it (inbounds are still the app's own, as for
 * an imported JSON). A broken text is never started: it is checked before saving and again before connecting.
 */
object GeekConfig {
    const val MAX_LENGTH = 512 * 1024

    /** Null when [text] can start the tunnel, otherwise what is wrong (in the user's language). */
    fun problem(text: String): String? {
        if (text.isBlank()) return tr("Пусто", "Empty", "Порожньо")
        if (text.length > MAX_LENGTH) return tr("Слишком большой конфиг", "The config is too big", "Завеликий конфіг")
        val json = try {
            JSONObject(text)
        } catch (e: org.json.JSONException) {
            return tr("Ошибка JSON: ", "JSON error: ", "Помилка JSON: ") + (e.message ?: "")
        }
        val outbounds = json.optJSONArray("outbounds")
        if (outbounds == null || outbounds.length() == 0) return tr("Нет «outbounds»", "No «outbounds»", "Немає «outbounds»")
        for (i in 0 until outbounds.length()) {
            val o =
                outbounds.optJSONObject(i)
                    ?: return tr("Выход №", "Outbound #", "Вихід №") + (i + 1) + tr(" — не объект", " is not an object", " — не об'єкт")
            if (o.optString("protocol").isBlank()) {
                return tr("У выхода №", "Outbound #", "У виходу №") + (i + 1) +
                    tr(" нет «protocol»", " has no «protocol»", " немає «protocol»")
            }
        }
        json.optJSONObject("routing")?.let { routing ->
            if (routing.has("rules") &&
                routing.optJSONArray("rules") == null
            ) {
                return tr("«routing.rules» — не массив", "«routing.rules» is not an array", "«routing.rules» — не масив")
            }
        }
        return null
    }

    /** The generated config, pretty-printed for editing. */
    fun pretty(raw: String): String = JSONObject(raw).toString(2)
}
