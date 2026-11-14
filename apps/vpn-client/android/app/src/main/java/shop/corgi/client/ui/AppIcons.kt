package shop.corgi.client.ui

import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager

/**
 * «Оформление → Иконка приложения»: the launcher shows the app through one of three activity-aliases (manifest); the
 * chosen one is enabled, the others disabled. The launcher may take a few seconds to redraw.
 */
object AppIcons {
    private val ALIASES = mapOf("corgi" to "LauncherCorgi", "night" to "LauncherNight", "mint" to "LauncherMint")

    fun apply(context: Context, icon: String) {
        val pm = context.packageManager
        // The chosen entry is switched on first, so the launcher never has none.
        for ((key, alias) in ALIASES.entries.sortedBy { if (it.key == icon) 0 else 1 }) {
            val component = ComponentName(context.packageName, "shop.corgi.client.ui.$alias")
            val state = if (key == icon) PackageManager.COMPONENT_ENABLED_STATE_ENABLED else PackageManager.COMPONENT_ENABLED_STATE_DISABLED
            if (pm.getComponentEnabledSetting(component) != state) pm.setComponentEnabledSetting(component, state, PackageManager.DONT_KILL_APP)
        }
    }
}
