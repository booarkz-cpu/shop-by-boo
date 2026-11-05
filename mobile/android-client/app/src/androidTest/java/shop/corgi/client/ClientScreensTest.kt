package shop.corgi.client

import android.content.Context
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import shop.corgi.client.data.Store
import shop.corgi.client.ui.MainActivity
import java.util.Locale

/** Screens of «Корги Люси: клиент» on an emulator: adding links, servers, routing rules, settings. No network. */
@RunWith(AndroidJUnit4::class)
class ClientScreensTest {
    @get:Rule val compose = createEmptyComposeRule()
    private var scenario: ActivityScenario<MainActivity>? = null
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private val links = "vless://11111111-2222-3333-4444-555555555555@nl.example.com:443?security=reality&pbk=KEY&sid=ab#Netherlands\n" +
        "trojan://secret@de.example.com:443#Germany"

    @Before fun clean() {
        Locale.setDefault(Locale.ENGLISH)
        context.getSharedPreferences("client", 0).edit().clear().commit()
        context.getSharedPreferences("client_vpn", 0).edit().clear().commit()
    }

    @After fun close() { scenario?.close() }

    private fun launch() { scenario = ActivityScenario.launch(MainActivity::class.java); compose.waitForIdle() }

    private fun exists(text: String) = assertTrue(text, compose.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty())

    @Test fun emptyStateAddsLinksThroughTheDialog() {
        launch()
        exists("Add a subscription")
        compose.onAllNodesWithText("Add")[0].performClick()
        compose.onNodeWithText("Paste").assertExists()
        compose.onNodeWithText("Cancel").performClick()
        Store(context).add(links)
        scenario?.close(); launch()
        exists("Links (2)")
    }

    @Test fun serversListAndChoice() {
        Store(context).add(links)
        launch()
        compose.onNodeWithText("Servers").performClick()
        exists("Fastest (automatic)"); exists("Netherlands"); exists("Germany"); exists("trojan")
        compose.onNodeWithText("Germany").performClick()
        assertEquals("1", Store(context).activeServer)
        compose.onNodeWithText("Home").performClick()
        exists("Germany")
    }

    @Test fun routingRulesAreAdded() {
        launch()
        compose.onNodeWithText("Routing").performClick()
        compose.onNodeWithText("Own rules").performClick()
        assertEquals("custom", Store(context).settings.routing)
        compose.onNodeWithText("example.com / 10.0.0.0/8 / geosite:category-ads-all").performTextInput("Example.com")
        compose.onNodeWithText("Add rule").performClick()
        exists("domain:example.com → direct")
        assertEquals("domain:example.com", Store(context).settings.rules.single().match)
    }

    @Test fun settingsSwitchesAndAppsMode() {
        launch()
        compose.onNodeWithText("Settings").performClick()
        compose.onNodeWithText("All but selected").performClick()
        assertEquals("except", Store(context).settings.appsMode)
        exists("Choose apps (0)")
        exists("Check for updates")
        exists("Open VPN settings")
    }
}
