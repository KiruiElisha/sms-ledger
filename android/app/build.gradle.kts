plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.smsledger.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.smsledger.app"
        minSdk = 24
        targetSdk = 35
        // CI stamps every build so a newer APK installs over the older one.
        versionCode = (System.getenv("VERSION_CODE") ?: "1").toInt()
        versionName = System.getenv("VERSION_NAME") ?: "0.1.0"
    }

    // Your own key when the SMS_LEDGER_KEYSTORE* secrets are set; otherwise the sideload key in this
    // folder, so every build can update the last one. Use your own key before sharing the APK widely.
    signingConfigs {
        create("release") {
            storeFile = file(System.getenv("SMS_LEDGER_KEYSTORE") ?: "sideload.keystore")
            storePassword = System.getenv("SMS_LEDGER_KEYSTORE_PASSWORD") ?: "android"
            keyAlias = System.getenv("SMS_LEDGER_KEY_ALIAS") ?: "sideload"
            keyPassword = System.getenv("SMS_LEDGER_KEY_PASSWORD") ?: "android"
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
}
