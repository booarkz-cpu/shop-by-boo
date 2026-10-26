package shop.remnawave.user

import android.content.Intent
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * UI tests of the customer app on the demo mode of the debug build (fixed data, no network):
 * the bundled layout, the tab bar, buttons and sections work end to end on a device.
 */
@RunWith(AndroidJUnit4::class)
class AppScreensTest {
    @get:Rule val compose = createEmptyComposeRule()
    private var scenario: ActivityScenario<MainActivity>? = null

    private fun launch(tab: String = "vpn", vpnOn: Boolean = false) {
        val intent = Intent(ApplicationProvider.getApplicationContext(), MainActivity::class.java)
            .putExtra("corgi_demo", true).putExtra("corgi_tab", tab).putExtra("corgi_lang", "ru").putExtra("corgi_vpn_on", vpnOn)
        scenario = ActivityScenario.launch(intent)
        compose.waitForIdle()
    }

    @After fun close() { scenario?.close() }

    @Test fun vpnScreenShowsConnectAndPlan() {
        launch()
        compose.onAllNodesWithText("Подключить").fetchSemanticsNodes().let { assertTrue("connect button", it.isNotEmpty()) }
        compose.onNodeWithText("Премиум · 12 месяцев").assertExists()
    }

    @Test fun connectTogglesTheStatus() {
        launch()
        compose.onNodeWithText("VPN отключён").assertExists()
        compose.onAllNodesWithText("Подключить")[0].performClick()
        compose.waitForIdle()
        compose.onNodeWithText("VPN подключён").assertExists()
    }

    @Test fun tabBarOpensPremiumWithPlans() {
        launch()
        compose.onAllNodesWithText("Премиум")[0].performClick()
        compose.waitForIdle()
        compose.onNodeWithText("12 месяцев").assertExists()
        compose.onNodeWithText("Оплатить").assertExists()
    }

    @Test fun giveawaysListAndHomePromo() {
        launch("giveaways")
        compose.onNodeWithText("Новогоднее колесо").assertExists()
        compose.onNodeWithText("Участвовать").assertExists()
        scenario?.close()
        launch("vpn")
        compose.onNodeWithText("Новогоднее колесо").assertExists() // the home promo banner
    }

    @Test fun settingsShowDocumentsAndSignOut() {
        launch("settings")
        compose.onNodeWithText("Документы").assertExists()
        compose.onNodeWithText("Выйти").assertExists()
    }
}
