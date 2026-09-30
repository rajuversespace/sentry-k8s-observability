# syntax=docker/dockerfile:1.6
# Init container for every JVM app: copies the Sentry Java agent into a shared
# emptyDir so the app container loads it with -javaagent. App images stay plain.
#
# The agent does not bundle async-profiler, and -javaagent only puts the agent jar
# itself on the classpath. So the profiler jars are merged INTO the agent jar here:
# one jar, one -javaagent flag, continuous profiling with zero app changes.
# (No class or service-file overlaps between these jars; checked for 8.58.0 / 4.4.)
#
# Keep SENTRY_VERSION equal to the io.sentry:* version apps compile against.
# SHA-256 values: taken from files verified against Maven Central's published SHA-1.

FROM alpine:3.20 AS merge
RUN apk add --no-cache zip unzip
ARG SENTRY_VERSION=8.58.0
ARG ASYNC_PROFILER_VERSION=4.4
ADD --checksum=sha256:b6d6cbaec6bd193e8d26a745df8cb3ab2462ff1a1f6a6bf70fd55156612d6f1a \
    https://repo1.maven.org/maven2/io/sentry/sentry-opentelemetry-agent/${SENTRY_VERSION}/sentry-opentelemetry-agent-${SENTRY_VERSION}.jar \
    /build/sentry-opentelemetry-agent.jar
ADD --checksum=sha256:90a05a412d33827dc399ebdae6474d86e2db90f6d6a137c60836a84a3f2f8fd6 \
    https://repo1.maven.org/maven2/io/sentry/sentry-async-profiler/${SENTRY_VERSION}/sentry-async-profiler-${SENTRY_VERSION}.jar \
    /build/extra/sentry-async-profiler.jar
ADD --checksum=sha256:47f321b8cdbadda2c281a612f6ac245254c81a02ce578abf782a53170ea40b37 \
    https://repo1.maven.org/maven2/tools/profiler/async-profiler/${ASYNC_PROFILER_VERSION}/async-profiler-${ASYNC_PROFILER_VERSION}.jar \
    /build/extra/async-profiler.jar
ADD --checksum=sha256:e8da0076f4b31224678e5a15201784aa219b5e1f2ed211fcdfb88f4df4d9ffbc \
    https://repo1.maven.org/maven2/tools/profiler/jfr-converter/${ASYNC_PROFILER_VERSION}/jfr-converter-${ASYNC_PROFILER_VERSION}.jar \
    /build/extra/jfr-converter.jar
WORKDIR /build/merged
# Unpack the extra jars (minus their manifests) and add them to the agent jar,
# keeping the agent's own manifest (Premain-Class etc.).
RUN for j in /build/extra/*.jar; do unzip -q -o "$j" -x 'META-INF/MANIFEST.MF'; done \
 && zip -q -r /build/sentry-opentelemetry-agent.jar . \
 && chmod 0644 /build/sentry-opentelemetry-agent.jar

FROM busybox:1.37
COPY --from=merge /build/sentry-opentelemetry-agent.jar /agent/sentry-opentelemetry-agent.jar
ENTRYPOINT ["cp", "/agent/sentry-opentelemetry-agent.jar", "/sentry/"]
