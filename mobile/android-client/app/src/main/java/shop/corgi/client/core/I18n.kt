package shop.corgi.client.core

import java.util.Locale

/** RU / EN / UK by the system language or the one chosen in «Оформление → Язык» (everything the user reads, errors included). */
fun tr(ru: String, en: String, uk: String): String = when (Locale.getDefault().language) { "ru" -> ru; "uk" -> uk; else -> en }

object I18n {
    private val system: Locale = Locale.getDefault()

    /** «system» brings back the phone's language; ru / en / uk make the app speak it. */
    fun apply(lang: String) { Locale.setDefault(if (lang == "system") system else Locale.forLanguageTag(lang)) }
}
