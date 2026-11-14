package shop.corgi.client.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class AppListTest {
    private val apps =
        listOf(
            AppEntry("org.telegram.messenger", "Telegram", false),
            AppEntry("com.google.android.youtube", "YouTube", false),
            AppEntry("com.android.chrome", "Chrome", true),
            AppEntry("ru.sberbankmobile", "СберБанк", false)
        )

    @Test fun searchTabsAndChosenFirst() {
        assertEquals(
            listOf("ru.sberbankmobile", "org.telegram.messenger", "com.google.android.youtube"),
            AppList.filter(apps, "", system = false, chosen = setOf("ru.sberbankmobile")).map { it.pkg }
        )
        assertEquals(listOf("com.android.chrome"), AppList.filter(apps, "", system = true, chosen = emptySet()).map { it.pkg })
        assertEquals(listOf("org.telegram.messenger"), AppList.filter(apps, "TELE", system = false, chosen = emptySet()).map { it.pkg })
        assertEquals(listOf("ru.sberbankmobile"), AppList.filter(apps, "сбер", system = false, chosen = emptySet()).map { it.pkg })
        assertEquals(
            "by package too",
            listOf("com.google.android.youtube"),
            AppList.filter(apps, "google", false, emptySet()).map {
                it.pkg
            }
        )
    }

    @Test fun exportAndImport() {
        val text = AppList.export("except", setOf("org.telegram.messenger", "com.android.chrome"))
        assertEquals("except" to setOf("org.telegram.messenger", "com.android.chrome"), AppList.import(text))
        val (mode, list) = AppList.import("[\"org.telegram.messenger\", \"not a package\", \"\"]")
        assertNull(mode)
        assertEquals(setOf("org.telegram.messenger"), list)
        assertEquals(null to setOf("a.b"), AppList.import("{\"mode\": \"all\", \"apps\": [\"a.b\"]}"))
        assertThrows(Exception::class.java) { AppList.import("hello") }
    }
}
