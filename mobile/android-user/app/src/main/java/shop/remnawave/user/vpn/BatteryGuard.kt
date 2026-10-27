package shop.remnawave.user.vpn

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings

/**
 * Firmware that stops background VPN services (MIUI/HyperOS, One UI, EMUI/MagicOS, ColorOS…).
 *
 * After the first connection on such a phone, while the app is still under battery optimisation,
 * the app shows once a hint with two buttons: the system «unrestricted battery» list and the
 * vendor's own autostart/background screen when it exists. Nothing is requested silently: the
 * app never asks for REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, the customer flips the switch.
 */
object BatteryGuard {
    private const val PREFS = "corgi_battery"
    private const val KEY_SHOWN = "hint_shown_for"

    /** Vendors whose firmware is known to kill foreground VPN services (dontkillmyapp.com). */
    private val AGGRESSIVE = setOf("xiaomi", "redmi", "poco", "samsung", "huawei", "honor", "oppo", "realme", "oneplus",
        "vivo", "iqoo", "meizu", "asus", "tecno", "infinix", "itel", "nothing", "lenovo", "motorola", "zte", "nubia")

    fun vendor(manufacturer: String = Build.MANUFACTURER, brand: String = Build.BRAND): String {
        val names = listOf(manufacturer, brand).map { it.lowercase().trim() }
        return names.firstOrNull { it in AGGRESSIVE } ?: names.first()
    }

    fun aggressive(manufacturer: String = Build.MANUFACTURER, brand: String = Build.BRAND): Boolean =
        vendor(manufacturer, brand) in AGGRESSIVE

    fun optimised(context: Context): Boolean {
        val power = context.getSystemService(PowerManager::class.java) ?: return false
        return !power.isIgnoringBatteryOptimizations(context.packageName)
    }

    /** Show the hint now? Once per app version, only on aggressive firmware, only while optimised. */
    fun shouldHint(context: Context, versionName: String): Boolean {
        if (!aggressive() || !optimised(context)) return false
        return context.getSharedPreferences(PREFS, 0).getString(KEY_SHOWN, "") != versionName
    }

    fun markShown(context: Context, versionName: String) {
        context.getSharedPreferences(PREFS, 0).edit().putString(KEY_SHOWN, versionName).apply()
    }

    /** Intents to try in order for «Батарея»; the first that resolves is opened. */
    fun batteryIntents(context: Context): List<Intent> = listOf(
        Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")),
    )

    /** The vendor's autostart / background-activity screen, when the firmware has one. */
    fun vendorIntents(context: Context): List<Intent> {
        val pkg = context.packageName
        val components = when (vendor()) {
            "xiaomi", "redmi", "poco" -> listOf(
                ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"),
                ComponentName("com.miui.powerkeeper", "com.miui.powerkeeper.ui.HiddenAppsConfigActivity"))
            "samsung" -> listOf(
                ComponentName("com.samsung.android.lool", "com.samsung.android.sm.battery.ui.BatteryActivity"),
                ComponentName("com.samsung.android.sm", "com.samsung.android.sm.ui.battery.BatteryActivity"))
            "huawei", "honor" -> listOf(
                ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
                ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity"))
            "oppo", "realme", "oneplus" -> listOf(
                ComponentName("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"),
                ComponentName("com.oplus.battery", "com.oplus.powermanager.fuelgaue.PowerUsageModelActivity"))
            "vivo", "iqoo" -> listOf(
                ComponentName("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
                ComponentName("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.BgStartUpManager"))
            "meizu" -> listOf(ComponentName("com.meizu.safe", "com.meizu.safe.security.SHOW_APPSEC"))
            "asus" -> listOf(ComponentName("com.asus.mobilemanager", "com.asus.mobilemanager.MainActivity"))
            else -> emptyList()
        }
        return components.map { Intent().setComponent(it).putExtra("package_name", pkg).putExtra("packageName", pkg) }
    }

    /** Opens the first intent that resolves on this phone; false when none does. */
    fun open(context: Context, intents: List<Intent>): Boolean {
        // No resolveActivity(): vendor packages are hidden by package visibility on Android 11+,
        // so each screen is simply tried; a missing or refusing one throws and the next is tried.
        for (intent in intents) {
            try {
                context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                return true
            } catch (_: Exception) {
                continue
            }
        }
        return false
    }

    const val GUIDE = "https://dontkillmyapp.com/"
}
