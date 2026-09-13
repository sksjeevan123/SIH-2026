plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.example.webrtccall"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.webrtccall"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    // WebRTC (maintained fork of Google's WebRTC Android SDK; package is still org.webrtc.*)
    implementation("io.getstream:stream-webrtc-android:1.3.10")

    // WebSocket client used to talk to the signaling server
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // JSON payloads for signaling messages
    implementation("org.json:json:20240303")

    // Coroutines (available if you extend the client with suspending calls)
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
