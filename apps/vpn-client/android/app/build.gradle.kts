import java.util.zip.ZipFile

// «Корги Люси: клиент» — the third Android app (v28.79.0, stage 18): a standalone VPN client on the shop's Xray engine
// for any subscriptions, not only the shop's. Separate from the customer (apps/vpn-shop/android) and administrator
// (apps/lucy-admin/android) apps: its own applicationId, tags and APK name; nothing here changes their builds.
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

val xrayAar = rootProject.file("../../vpn-shop/android/app/libs/libv2ray.aar")
val pinFile = rootProject.file("../../../scripts/mobile/build-xray-aar.sh")
val pinnedRevision = pinFile.takeIf { it.isFile }?.let {
    Regex("XRAY_AAR_COMMIT:-([0-9a-f]{40})").find(it.readText())?.groupValues?.get(1)
}
val packagedRevision = if (xrayAar.isFile) {
    ZipFile(xrayAar).use { archive ->
        val marker = archive.getEntry("assets/corgi-xray.commit")
            ?: error("Rebuild the shared libv2ray.aar to record its source revision")
        archive.getInputStream(marker).bufferedReader().use { it.readText().trim() }
            .also { check(it.matches(Regex("[0-9a-f]{40}"))) { "Invalid Xray source marker" } }
    }
} else null

// Keep engine-free debug builds available. Release APKs and bundles require the pinned engine.
tasks.matching { it.name == "preReleaseBuild" }.configureEach {
    doFirst {
        check(packagedRevision != null && packagedRevision == pinnedRevision) { "Build the pinned shared AAR with scripts/mobile/build-xray-aar.sh" }
    }
}

android {
    namespace = "shop.corgi.client"
    compileSdk = 37
    defaultConfig {
        applicationId = "shop.corgi.client"
        minSdk = 26
        targetSdk = 36
        versionCode = 1101
        versionName = "1.10.1"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "XRAY_AAR_COMMIT", "\"${packagedRevision ?: "unknown"}\"")
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
        // gomobile already stripped this library. Preserve the bytes recorded by the AAR build.
        jniLibs.keepDebugSymbols += "**/libgojni.so"
    }
    signingConfigs {
        create("shopRelease") {
            val store = System.getenv("ANDROID_KEYSTORE")
            if (!store.isNullOrBlank()) {
                storeFile = file(store)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        debug {
            applicationIdSuffix = ".preview"
            versionNameSuffix = "-preview"
        }
        release {
            isMinifyEnabled = false
            if (!System.getenv("ANDROID_KEYSTORE").isNullOrBlank()) signingConfig = signingConfigs.getByName("shopRelease")
        }
    }
    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    // v1.5.0: the main screen's view model (MVVM, StateFlow) and its previews in the IDE.
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    // QR: scanning through Google's code scanner (no camera permission), drawing with ZXing core (Apache-2.0).
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")
    // Play services pull an old Fragment; the activity-result API needs 1.3+.
    implementation("androidx.fragment:fragment:1.9.1")
    implementation("com.google.zxing:core:3.5.4")
    // The VPN engine: Xray-core through libv2ray.aar (scripts/mobile/build-xray-aar.sh), the same as the customer app.
    if (xrayAar.isFile) implementation(files(xrayAar))
    // UI tests (app/src/androidTest): Compose testing on an emulator in CI (android-client.yml).
    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:core-ktx:1.7.0")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20260814")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
}
