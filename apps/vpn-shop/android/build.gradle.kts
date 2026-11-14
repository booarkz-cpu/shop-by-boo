// AGP 9 builds Kotlin itself; the Kotlin plugin stays here (not applied) to pin the Kotlin and Compose compiler version.
plugins {
    id("com.android.application") version "9.5.1" apply false
    id("org.jetbrains.kotlin.android") version "2.4.21" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.21" apply false
}
