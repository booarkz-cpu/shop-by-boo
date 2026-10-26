plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "shop.remnawave.user"
    compileSdk = 35
    defaultConfig {
        applicationId = "shop.remnawave.user"
        minSdk = 26
        targetSdk = 35
        versionCode = 3000
        versionName = "3.0.0"
        // Historical compatibility marker: versionName = "2.9.0"
        // Firebase client identifiers for FCM push (public values, not secrets).
        // Empty values build the app without push; see docs/ru/PUSH_NOTIFICATIONS_CURRENT.md.
        fun firebase(name: String): String =
            ((project.findProperty("corgi.firebase.$name") as String?) ?: System.getenv("CORGI_FIREBASE_${name.uppercase()}") ?: "")
                .replace("\\", "").replace("\"", "")
        buildConfigField("String", "FIREBASE_APP_ID", "\"${firebase("app_id")}\"")
        buildConfigField("String", "FIREBASE_API_KEY", "\"${firebase("api_key")}\"")
        buildConfigField("String", "FIREBASE_PROJECT_ID", "\"${firebase("project_id")}\"")
        buildConfigField("String", "FIREBASE_SENDER_ID", "\"${firebase("sender_id")}\"")
        // Shop address baked into the build: the sign-in screen then has no «Адрес магазина» field.
        // -Pcorgi.shop_url=https://api.example.com or CORGI_SHOP_URL; empty keeps the field.
        val shopUrl = ((project.findProperty("corgi.shop_url") as String?) ?: System.getenv("CORGI_SHOP_URL") ?: "")
            .trim().trimEnd('/').replace("\\", "").replace("\"", "")
        require(shopUrl.isEmpty() || shopUrl.startsWith("https://")) { "corgi.shop_url must start with https://" }
        buildConfigField("String", "SHOP_URL", "\"$shopUrl\"")
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
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
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    // Icons of the layout buttons and tabs (backend/app/mobile_layout.py ICONS).
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.biometric:biometric:1.1.0")
    // FCM without the google-services plugin: FirebaseApp is initialised from BuildConfig.
    implementation("com.google.firebase:firebase-messaging:24.1.0")
    // Passkeys: Credential Manager (Play services provider for Android 9-13, platform on 14+).
    implementation("androidx.credentials:credentials:1.3.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.3.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
