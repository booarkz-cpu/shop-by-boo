package shop.remnawave.user

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import shop.remnawave.user.vpn.BatteryGuard

/** Which phones get the «VPN может отключаться в фоне» hint, and that it is shown once per version. */
@RunWith(AndroidJUnit4::class)
class BatteryGuardTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test
    fun aggressiveFirmwareIsRecognisedByManufacturerOrBrand() {
        assertTrue(BatteryGuard.aggressive("Xiaomi", "Redmi"))
        assertTrue(BatteryGuard.aggressive("samsung", "samsung"))
        assertTrue(BatteryGuard.aggressive("HUAWEI", "HONOR"))
        assertTrue(BatteryGuard.aggressive("Google", "POCO"))
        assertFalse(BatteryGuard.aggressive("Google", "google"))
        assertEquals("redmi", BatteryGuard.vendor("Unknown", "Redmi"))
    }

    @Test
    fun theSystemBatteryListIsAlwaysOffered() {
        val intents = BatteryGuard.batteryIntents(context)
        assertEquals(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS, intents.first().action)
        assertTrue(intents.last().data.toString().endsWith(context.packageName))
    }

    @Test
    fun theHintIsShownOncePerVersion() {
        // The emulator is a Google image: never «aggressive», so no hint at all.
        assertFalse(BatteryGuard.shouldHint(context, "test-1"))
        BatteryGuard.markShown(context, "test-1")
        assertFalse(BatteryGuard.shouldHint(context, "test-1"))
    }
}
