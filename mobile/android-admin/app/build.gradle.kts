plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "shop.remnawave.admin"
    compileSdk = 37
    defaultConfig {
        applicationId = "shop.remnawave.admin"
        minSdk = 26
        targetSdk = 36
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        versionCode = 3600
        versionName = "3.6.0"
        // Historical compatibility marker: versionName = "2.9.0"
        // v28.77.0: the shop's API address baked into the build (-Pcorgi.shop_url or CORGI_SHOP_URL, see
        // mobile/shop-url.txt): a new profile starts with it, so the administrator does not type it.
        val shopUrl = ((project.findProperty("corgi.shop_url") as String?) ?: System.getenv("CORGI_SHOP_URL") ?: "").trim().trimEnd('/')
        require(shopUrl.isEmpty() || shopUrl.startsWith("https://")) { "corgi.shop_url must start with https://" }
        buildConfigField("String", "SHOP_URL", "\"$shopUrl\"")
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
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
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.biometric:biometric:1.1.0")
    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:core-ktx:1.7.0")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
