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
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
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

    /** Scrolls to the element first when it is in a scrollable screen: a tap outside the visible area hits nothing. */
    private fun androidx.compose.ui.test.SemanticsNodeInteraction.tap() {
        runCatching { performScrollTo() }
        // The node's own click action: a touch can land on another element when the screen is still settling.
        if (fetchSemanticsNode().config.contains(androidx.compose.ui.semantics.SemanticsActions.OnClick))
            performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.OnClick) else performClick()
        compose.waitForIdle()
    }

    private fun exists(text: String) = assertTrue(text, compose.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty())

    @Test fun emptyStateAddsLinksThroughTheDialog() {
        launch()
        exists("Add a subscription")
        compose.onAllNodesWithText("Add")[0].tap()
        exists("Scan QR")
        compose.onNodeWithText("Cancel").tap()
        Store(context).add(links)
        scenario?.close(); launch()
        exists("Links (2)")
        exists("Current provider".uppercase())
    }

    @Test fun serversListSearchFilterAndChoice() {
        Store(context).add(links)
        launch()
        compose.onNodeWithText("Servers").tap()
        exists("Auto select"); exists("Netherlands"); exists("Germany"); exists("REALITY")
        compose.onAllNodesWithText("TROJAN")[0].tap()          // the protocol chip comes first
        assertTrue(compose.onAllNodesWithText("Netherlands").fetchSemanticsNodes().isEmpty())
        compose.onNodeWithText("All").tap()
        compose.onNodeWithTag("search").performTextInput("neth")
        assertTrue(compose.onAllNodesWithText("Germany").fetchSemanticsNodes().isEmpty())
        compose.onNodeWithText("Netherlands").tap()
        assertEquals("0", Store(context).activeServer)
        compose.onNodeWithText("Home").tap()
        exists("Netherlands")
    }

    @Test fun routingRulesAreAddedFromTheSettingsMenu() {
        launch()
        compose.onNodeWithText("Settings").tap()
        compose.onNodeWithText("Routing").tap()
        compose.onNodeWithText("Own rules").tap()
        assertEquals("custom", Store(context).settings.routing)
        compose.onNodeWithText("example.com / 10.0.0.0/8 / geosite:category-ads-all").performTextInput("Example.com")
        compose.onNodeWithText("Add rule").tap()
        exists("domain:example.com → direct")
        assertEquals("domain:example.com", Store(context).settings.rules.single().match)
    }

    @Test fun everySettingsPageOpensAndSaves() {
        launch()
        compose.onNodeWithText("Settings").tap()
        exists("Everything under your control")   // the brand banner
        compose.onNodeWithText("Per-app proxy").tap()
        compose.onNodeWithText("All but selected").tap()
        assertEquals("except", Store(context).settings.appsMode)
        exists("Choose apps (0)")
        compose.onNodeWithTag("back").tap()

        compose.onNodeWithText("Appearance").tap()
        compose.onNodeWithText("AMOLED black").tap()
        assertTrue(Store(context).settings.amoled)
        compose.onNodeWithText("Compact").tap()
        assertEquals("compact", Store(context).settings.connectStyle)
        compose.onNodeWithTag("back").tap()

        compose.onNodeWithText("Tunnel").tap()
        compose.onNodeWithText("Block UDP").tap()
        assertTrue(Store(context).settings.blockUdp)
        compose.onNodeWithTag("back").tap()

        compose.onNodeWithText("Provider settings").tap()
        compose.onNodeWithText("Ping on launch").tap()
        assertTrue(Store(context).settings.pingOnLaunch)
        compose.onNodeWithText("By name").tap()
        assertEquals("name", Store(context).settings.sort)
        compose.onNodeWithTag("back").tap()

        compose.onNodeWithText("Ping settings").tap()
        compose.onNodeWithText("TCP Connect").tap()
        assertEquals("tcp", Store(context).settings.pingMethod)
        compose.onNodeWithText("Dots").tap()
        assertEquals("dots", Store(context).settings.pingDisplay)
        compose.onNodeWithTag("back").tap()

        compose.onNodeWithText("Connection").tap()
        exists("Block internet without the VPN")
        compose.onNodeWithTag("back").tap()

        compose.onNodeWithText("About").tap()
        exists("HWID"); exists(Store(context).hwid)
        exists("Check for updates")
    }

    @Test fun proxyModeSchemesBackupAndLogsPages() {
        launch()
        compose.onNodeWithText("Settings").tap()
        compose.onNodeWithText("Tunnel").tap()
        compose.onNodeWithText("Proxy only").tap()
        assertEquals("proxy", Store(context).settings.tunnelMode)
        exists("Hotspot access"); exists(Store(context).settings.proxyUser)
        compose.onNodeWithText("Hotspot access").tap()
        assertTrue(Store(context).settings.shareLan && Store(context).settings.proxyAuth)
        compose.onNodeWithTag("back").tap()
        compose.onNodeWithText("URL schemes").tap()
        exists("corgi://toggle"); exists("corgi://routing/onadd/{base64}")
        compose.onNodeWithTag("back").tap()
        compose.onNodeWithText("Backup").tap()
        exists("Export"); exists("Choose a file")
        compose.onNodeWithTag("back").tap()
        compose.onNodeWithText("Tunnel logs").tap()
        compose.onNodeWithText("debug").tap()
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
        compose.onNodeWithTag("restore-confirm").tap()
        compose.waitForIdle()
        assertEquals(1, Store(context).profiles.size)
    }

    @Test fun appIconAndRoutingProfiles() {
        launch()
        compose.onNodeWithText("Settings").tap()
        compose.onNodeWithText("Appearance").tap()
        compose.onNodeWithTag("icon-night").tap()
        assertEquals("night", Store(context).settings.appIcon)
        val pm = context.packageManager
        assertEquals(android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
            pm.getComponentEnabledSetting(android.content.ComponentName(context, "shop.corgi.client.ui.LauncherNight")))
        assertEquals(android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
            pm.getComponentEnabledSetting(android.content.ComponentName(context, "shop.corgi.client.ui.LauncherCorgi")))
        compose.onNodeWithTag("icon-corgi").tap()
        compose.onNodeWithTag("back").tap()
        compose.onNodeWithText("Routing").tap()
        compose.onNodeWithText("Russian sites direct").tap()
        compose.onNodeWithTag("profile-name").performTextInput("Home")
        compose.onNodeWithText("Save current").tap()
        compose.onNodeWithText("Everything").tap()
        assertEquals("global", Store(context).settings.routing)
        compose.onNodeWithTag("routing-profile").tap()
        assertEquals("bypass_ru", Store(context).settings.routing)
        assertEquals(listOf("Home"), Store(context).settings.routingProfiles.map { it.name })
    }

    @Test fun homeServerCardOpensTheListAndChooses() {
        Store(context).add(links)
        launch()
        exists("Free internet without the extra Woof!")
        exists("Auto select")
        shot("home")
        compose.onNodeWithTag("server-picker").tap()   // the card opens the list
        compose.waitForIdle()
        assertTrue(compose.onAllNodesWithTag("server-row").fetchSemanticsNodes().size == 3)   // auto + 2 servers
        exists("VLESS • TCP • REALITY")
        shot("home-servers")
        compose.onNodeWithText("Germany").tap()
        assertEquals("1", Store(context).activeServer)
        assertTrue(compose.onAllNodesWithTag("server-row").fetchSemanticsNodes().isEmpty())   // closed after the choice
        exists("Germany")
        compose.onNodeWithText("Settings").tap()
        shot("settings")
    }

    /** v1.5.0: the main screen of the owner's prompt — every part is there and the ad blocking switch works. */
    @Test fun mainScreenPartsAndAdBlocking() {
        Store(context).add(links)
        context.getSharedPreferences("client_streak", 0).edit().clear().commit()
        launch()
        for (tag in listOf("slogan", "streak", "share", "banner-app-vpn", "status", "connect", "adblock", "server-picker")) {
            assertTrue(tag, compose.onAllNodesWithTag(tag).fetchSemanticsNodes().isNotEmpty())
        }
        exists("Free internet without the extra Woof!"); exists("PROTECTION IN ONE TAP"); exists("Unlimited"); exists("Disconnected")
        exists("0 days")
        assertTrue("no stats while disconnected", compose.onAllNodesWithTag("stats").fetchSemanticsNodes().isEmpty())
        // The slogan is right under the name: above the banner.
        val slogan = compose.onNodeWithTag("slogan").fetchSemanticsNode().boundsInRoot
        val banner = compose.onNodeWithTag("banner-app-vpn").fetchSemanticsNode().boundsInRoot
        assertTrue("slogan above the banner", slogan.bottom <= banner.top)
        shot("home-v150")
        // Without geosite.dat the switch explains what is needed and stays off.
        compose.onNodeWithTag("adblock").tap()
        exists("Geo files needed")
        assertEquals(false, Store(context).settings.adBlock)
        // With the files it turns on and is kept in the settings (the config gets the block rule — AdBlockTest).
        java.io.File(context.filesDir, "geoip.dat").writeText("x"); java.io.File(context.filesDir, "geosite.dat").writeText("x")
        compose.onNodeWithTag("adblock").tap()
        assertEquals(true, Store(context).settings.adBlock)
        java.io.File(context.filesDir, "geoip.dat").delete(); java.io.File(context.filesDir, "geosite.dat").delete()
        Store(context).settings = Store(context).settings.copy(adBlock = false)
    }

    /** Screens for the owner (pulled by android-client.yml from the app's external files into an artifact). */
    private fun shot(name: String) {
        compose.waitForIdle()
        val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
        val png = java.io.ByteArrayOutputStream().also { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        // The shell user (not the app) writes into /data/local/tmp, which the workflow pulls: the bytes go through its stdin.
        val automation = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().uiAutomation
        android.os.ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand("mkdir -p /data/local/tmp/client-screens")).use { it.readBytes() }
        // No shell here (arguments are split on spaces, no redirection): dd writes its stdin to the file.
        val (out, input) = automation.executeShellCommandRw("dd of=/data/local/tmp/client-screens/$name.png").let { it[0] to it[1] }
        android.os.ParcelFileDescriptor.AutoCloseOutputStream(input).use { it.write(png) }
        android.os.ParcelFileDescriptor.AutoCloseInputStream(out).use { it.readBytes() }
        Thread.sleep(300)
    }

    @Test fun resetBringsDefaultsBackAndKeepsProfiles() {
        val store = Store(context)
        store.add(links)
        store.settings = store.settings.copy(blockUdp = true, sort = "ping")
        launch()
        compose.onNodeWithText("Settings").tap()
        compose.onNodeWithTag("reset").tap()
        compose.onNodeWithText("Reset").tap()
        compose.waitForIdle()
        assertEquals(false, Store(context).settings.blockUdp)
        assertEquals(1, Store(context).profiles.size)
    }
}
