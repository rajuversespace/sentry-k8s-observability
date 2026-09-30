plugins {
    kotlin("jvm") version "2.0.21"
    application
}

repositories {
    mavenCentral()
}

// Must equal the Sentry agent version injected by the sentry-agent-init container.
val sentryVersion = "8.58.0"

dependencies {
    implementation("org.web3j:core:4.14.0")
    implementation("ch.qos.logback:logback-classic:1.5.12")

    // The Sentry agent (with profiler merged in) provides the SDK at runtime;
    // compile against it only.
    compileOnly("io.sentry:sentry:$sentryVersion")

    // prom-bridge: parses Prometheus HTTP API responses.
    implementation("com.fasterxml.jackson.core:jackson-databind:2.22.3")
}

kotlin {
    jvmToolchain(21)
}

application {
    mainClass.set("rpclogger.MainKt")
}
