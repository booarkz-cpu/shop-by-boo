package shop.corgi.client

import android.content.Context
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
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
        exists("Scan QR")
        compose.onNodeWithText("Cancel").performClick()
        Store(context).add(links)
        scenario?.close(); launch()
        exists("Links (2)")
        exists("Current provider".uppercase())
    }

    @Test fun serversListSearchFilterAndChoice() {
        Store(context).add(links)
        launch()
        compose.onNodeWithText("Servers").performClick()
        exists("Auto select"); exists("Netherlands"); exists("Germany"); exists("REALITY")
        compose.onAllNodesWithText("TROJAN")[0].performClick()          // the protocol chip comes first
        assertTrue(compose.onAllNodesWithText("Netherlands").fetchSemanticsNodes().isEmpty())
        compose.onNodeWithText("All").performClick()
        compose.onNodeWithTag("search").performTextInput("neth")
        assertTrue(compose.onAllNodesWithText("Germany").fetchSemanticsNodes().isEmpty())
        compose.onNodeWithText("Netherlands").performClick()
        assertEquals("0", Store(context).activeServer)
        compose.onNodeWithText("Home").performClick()
        exists("Netherlands")
    }

    @Test fun routingRulesAreAddedFromTheSettingsMenu() {
        launch()
        compose.onNodeWithText("Settings").performClick()
        compose.onNodeWithText("Routing").performClick()
        compose.onNodeWithText("Own rules").performClick()
        assertEquals("custom", Store(context).settings.routing)
        compose.onNodeWithText("example.com / 10.0.0.0/8 / geosite:category-ads-all").performTextInput("Example.com")
        compose.onNodeWithText("Add rule").performClick()
        exists("domain:example.com → direct")
        assertEquals("domain:example.com", Store(context).settings.rules.single().match)
    }

    @Test fun everySettingsPageOpensAndSaves() {
        launch()
        compose.onNodeWithText("Settings").performClick()
        exists("Everything under your control")   // the brand banner
        compose.onNodeWithText("Per-app proxy").performClick()
        compose.onNodeWithText("All but selected").performClick()
        assertEquals("except", Store(context).settings.appsMode)
        exists("Choose apps (0)")
        compose.onNodeWithTag("back").performClick()

        compose.onNodeWithText("Appearance").performClick()
        compose.onNodeWithText("AMOLED black").performClick()
        assertTrue(Store(context).settings.amoled)
        compose.onNodeWithText("Compact").performClick()
        assertEquals("compact", Store(context).settings.connectStyle)
        compose.onNodeWithTag("back").performClick()

        compose.onNodeWithText("Tunnel").performClick()
        compose.onNodeWithText("Block UDP").performClick()
        assertTrue(Store(context).settings.blockUdp)
        compose.onNodeWithTag("back").performClick()

        compose.onNodeWithText("Provider settings").performClick()
        compose.onNodeWithText("Ping on launch").performClick()
        assertTrue(Store(context).settings.pingOnLaunch)
        compose.onNodeWithText("By name").performClick()
        assertEquals("name", Store(context).settings.sort)
        compose.onNodeWithTag("back").performClick()

        compose.onNodeWithText("Ping settings").performClick()
        compose.onNodeWithText("TCP Connect").performClick()
        assertEquals("tcp", Store(context).settings.pingMethod)
        compose.onNodeWithText("Dots").performClick()
        assertEquals("dots", Store(context).settings.pingDisplay)
        compose.onNodeWithTag("back").performClick()

        compose.onNodeWithText("Connection").performClick()
        exists("Block internet without the VPN")
        compose.onNodeWithTag("back").performClick()

        compose.onNodeWithText("About").performClick()
        exists("HWID"); exists(Store(context).hwid)
        exists("Check for updates")
    }

    @Test fun proxyModeSchemesBackupAndLogsPages() {
        launch()
        compose.onNodeWithText("Settings").performClick()
        compose.onNodeWithText("Tunnel").performClick()
        compose.onNodeWithText("Proxy only").performClick()
        assertEquals("proxy", Store(context).settings.tunnelMode)
        exists("Hotspot access"); exists(Store(context).settings.proxyUser)
        compose.onNodeWithText("Hotspot access").performClick()
        assertTrue(Store(context).settings.shareLan && Store(context).settings.proxyAuth)
        compose.onNodeWithTag("back").performClick()
        compose.onNodeWithText("URL schemes").performClick()
        exists("corgi://toggle"); exists("corgi://routing/onadd/{base64}")
        compose.onNodeWithTag("back").performClick()
        compose.onNodeWithText("Backup").performClick()
        exists("Export"); exists("Choose a file")
        compose.onNodeWithTag("back").performClick()
        compose.onNodeWithText("Tunnel logs").performClick()
        compose.onNodeWithText("debug").performClick()
        assertEquals("debug", Store(context).settings.logLevel)
    }

    @Test fun restoreLinkIsConfirmedFirst() {
        val store = Store(context)
        store.add(links)
        val link = store.backup().link()
        store.profiles.forEach { store.remove(it.id) }
        scenario = ActivityScenario.launch(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(link))
            .setClassName(context, "shop.corgi.client.ui.MainActivity"))
        compose.waitForIdle()
        exists("Restore?"); exists("Links (2) — 2")
        assertEquals(0, Store(context).profiles.size)   // nothing changes before the confirmation
        compose.onNodeWithTag("restore-confirm").performClick()
        compose.waitForIdle()
        assertEquals(1, Store(context).profiles.size)
    }

    @Test fun appIconAndRoutingProfiles() {
        launch()
        compose.onNodeWithText("Settings").performClick()
        compose.onNodeWithText("Appearance").performClick()
        compose.onNodeWithTag("icon-night").performClick()
        assertEquals("night", Store(context).settings.appIcon)
        val pm = context.packageManager
        assertEquals(android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
            pm.getComponentEnabledSetting(android.content.ComponentName(context, "shop.corgi.client.ui.LauncherNight")))
        assertEquals(android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
            pm.getComponentEnabledSetting(android.content.ComponentName(context, "shop.corgi.client.ui.LauncherCorgi")))
        compose.onNodeWithTag("icon-corgi").performClick()
        compose.onNodeWithTag("back").performClick()
        compose.onNodeWithText("Routing").performClick()
        compose.onNodeWithText("Russian sites direct").performClick()
        compose.onNodeWithTag("profile-name").performTextInput("Home")
        compose.onNodeWithText("Save current").performClick()
        compose.onNodeWithText("Everything").performClick()
        assertEquals("global", Store(context).settings.routing)
        compose.onNodeWithTag("routing-profile").performClick()
        assertEquals("bypass_ru", Store(context).settings.routing)
        assertEquals(listOf("Home"), Store(context).settings.routingProfiles.map { it.name })
    }

    @Test fun homeServerCardOpensTheListAndChooses() {
        Store(context).add(links)
        launch()
        exists("Free internet without the extra Woof!")
        exists("Auto select")
        shot("home")
        compose.onNodeWithTag("server-picker").performClick()   // the card opens the list
        compose.waitForIdle()
        assertTrue(compose.onAllNodesWithTag("server-row").fetchSemanticsNodes().size == 3)   // auto + 2 servers
        exists("VLESS • TCP • REALITY")
        shot("home-servers")
        compose.onNodeWithText("Germany").performClick()
        assertEquals("1", Store(context).activeServer)
        assertTrue(compose.onAllNodesWithTag("server-row").fetchSemanticsNodes().isEmpty())   // closed after the choice
        exists("Germany")
        compose.onNodeWithText("Settings").performClick()
        shot("settings")
    }

    /** Screens for the owner (pulled by android-client.yml from the app's external files into an artifact). */
    private fun shot(name: String) {
        compose.waitForIdle()
        val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
        val dir = java.io.File(context.getExternalFilesDir(null), "screens").apply { mkdirs() }
        val file = java.io.File(dir, "$name.png")
        java.io.FileOutputStream(file).use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
        // The test run uninstalls the app (and its files): a copy goes to /data/local/tmp, which the workflow pulls.
        androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().uiAutomation
            .executeShellCommand("sh -c 'mkdir -p /data/local/tmp/client-screens && cp ${file.absolutePath} /data/local/tmp/client-screens/'").close()
        Thread.sleep(300)
    }

    @Test fun resetBringsDefaultsBackAndKeepsProfiles() {
        val store = Store(context)
        store.add(links)
        store.settings = store.settings.copy(blockUdp = true, sort = "ping")
        launch()
        compose.onNodeWithText("Settings").performClick()
        compose.onNodeWithTag("reset").performClick()
        compose.onNodeWithText("Reset").performClick()
        compose.waitForIdle()
        assertEquals(false, Store(context).settings.blockUdp)
        assertEquals(1, Store(context).profiles.size)
    }
}
