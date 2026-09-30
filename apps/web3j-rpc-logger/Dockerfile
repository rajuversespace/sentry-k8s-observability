FROM gradle:8.14-jdk21 AS build
WORKDIR /src
# Docker Desktop has no IPv6 route; stop the JVM from trying it.
ENV GRADLE_OPTS="-Djava.net.preferIPv4Stack=true"
COPY settings.gradle.kts build.gradle.kts ./
COPY src ./src
RUN gradle installDist --no-daemon --console=plain

FROM eclipse-temurin:21-jre
COPY --from=build /src/build/install/web3j-rpc-logger /app
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75"
ENTRYPOINT ["/app/bin/web3j-rpc-logger"]
