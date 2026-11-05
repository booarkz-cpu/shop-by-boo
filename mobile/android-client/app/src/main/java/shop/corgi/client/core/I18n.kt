package shop.corgi.client.core

import java.util.Locale

/** RU / EN / UK by the system language (everything the user reads, errors included). */
fun tr(ru: String, en: String, uk: String): String = when (Locale.getDefault().language) { "ru" -> ru; "uk" -> uk; else -> en }
