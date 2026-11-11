package shop.remnawave.admin

import android.content.Intent
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** UI tests of the administrator app in its demo mode (Remna Dark screens with fixed data). */
@RunWith(AndroidJUnit4::class)
class AdminScreensTest {
    @get:Rule val compose = createEmptyComposeRule()
    private var scenario: ActivityScenario<MainActivity>? = null

    private fun launch(tab: String) {
        val intent = Intent(ApplicationProvider.getApplicationContext(), MainActivity::class.java)
            .putExtra("corgi_demo", true).putExtra("corgi_tab", tab)
        scenario = ActivityScenario.launch(intent)
        compose.waitForIdle()
    }

    @After fun close() { scenario?.close() }

    /** v3.6.0: the admin app's own update check reads the manifest of the latest shop release. */
    @Test fun updateManifestIsCheckedStrictly() {
        val update = shop.remnawave.admin.update.AppUpdate
        val sha = "b".repeat(64)
        val apk = "https://github.com/booarkz-cpu/shop-by-boo/releases/latest/download/corgi-lusi-android-admin.apk"
        val good = """{"versionCode":3700,"versionName":"3.7.0","sha256":"$sha","apk":"$apk"}"""
        org.junit.Assert.assertEquals("3.7.0", update.newer(good, 3600)?.versionName)
        org.junit.Assert.assertNull(update.newer(good, 3700))
        org.junit.Assert.assertTrue(runCatching { update.parse(good.replace("corgi-lusi-android-admin.apk", "corgi-lusi-android.apk")) }.isFailure)
        org.junit.Assert.assertTrue(update.fromStore("com.android.vending"))
        org.junit.Assert.assertFalse(update.fromStore(null))
    }

    @Test fun overviewShowsKpis() {
        launch("overview")
        compose.onNodeWithText("1284").assertExists()
        compose.onNodeWithText("5320").assertExists()
    }

    @Test fun navigationOpensPaymentsAndMonitoring() {
        launch("overview")
        compose.onAllNodesWithText("Платежи")[0].performClick()
        compose.waitForIdle()
        compose.onNodeWithText("#1284 · 1499 RUB").assertExists()
        launch("monitoring")
        compose.onNodeWithText("Амстердам").assertExists()
        compose.onNodeWithText("offline").assertExists()
    }

    @Test fun launchChecklistShowsMissingSteps() {
        launch("launch")
        compose.onNodeWithText("Чеки в налоговую").assertExists()
    }
}
