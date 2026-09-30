package rpclogger

import com.fasterxml.jackson.databind.ObjectMapper
import io.sentry.Sentry
import io.sentry.metrics.SentryMetricsParameters
import java.io.File
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/**
 * prom-bridge: forwards Prometheus data to Sentry Metrics.
 *
 * Sentry has no Prometheus remote-write or OTLP-metrics ingest, so this runs each
 * configured PromQL query against the Prometheus HTTP API on an interval and sends
 * every resulting series as a Sentry gauge, with the Prometheus labels as attributes.
 * Counters should be wrapped in rate()/increase() in the query, not forwarded raw.
 */

/** One line of the queries file: `<sentry.metric.name>|<unit>|<PromQL>`. */
data class BridgeQuery(val name: String, val unit: String, val promql: String)

fun loadQueries(file: File): List<BridgeQuery> = file.readLines()
    .map { it.trim() }
    .filter { it.isNotEmpty() && !it.startsWith("#") }
    .map { line ->
        val parts = line.split("|", limit = 3)
        require(parts.size == 3) { "Bad query line (want name|unit|promql): $line" }
        BridgeQuery(parts[0].trim(), parts[1].trim(), parts[2].trim())
    }

fun main() {
    val promUrl = System.getenv("PROMETHEUS_URL") ?: "http://prometheus:9090"
    val intervalSec = System.getenv("BRIDGE_INTERVAL")?.toLongOrNull() ?: 15L
    val queries = loadQueries(File(System.getenv("QUERIES_FILE") ?: "/etc/prom-bridge/queries.txt"))

    // Sentry is initialised by the injected Sentry Java agent (see k8s/platform/prom-bridge.yaml).
    val bridge = PromBridge(promUrl)
    Log.info("prom-bridge started | prometheus: $promUrl | ${queries.size} queries every ${intervalSec}s")
    while (true) {
        var forwarded = 0
        for (q in queries) {
            try {
                forwarded += bridge.forward(q)
            } catch (e: Exception) {
                Sentry.metrics().count("prom_bridge.query.errors", 1.0, "none", attrs("sentry.metric" to q.name))
                Log.warn("Query ${q.name} failed: ${e.message}")
            }
        }
        Sentry.metrics().gauge("prom_bridge.series.forwarded", forwarded.toDouble())
        Thread.sleep(intervalSec * 1000)
    }
}

class PromBridge(private val promUrl: String) {
    private val http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build()
    private val json = ObjectMapper()

    /** Runs one instant query and sends each series to Sentry. Returns the series count. */
    fun forward(q: BridgeQuery): Int {
        val uri = URI("$promUrl/api/v1/query?query=" + URLEncoder.encode(q.promql, Charsets.UTF_8))
        val resp = http.send(HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(10)).GET().build(),
            HttpResponse.BodyHandlers.ofString())
        val body = json.readTree(resp.body())
        check(resp.statusCode() == 200 && body.path("status").asText() == "success") {
            "HTTP ${resp.statusCode()}: ${body.path("error").asText(resp.body().take(200))}"
        }
        val data = body.path("data")
        check(data.path("resultType").asText() == "vector") { "expected vector result, got ${data.path("resultType")}" }

        var sent = 0
        for (series in data.path("result")) {
            val value = series.path("value").path(1).asText().toDoubleOrNull() ?: continue
            if (value.isNaN() || value.isInfinite()) continue
            val labels = mutableMapOf<String, Any>()
            series.path("metric").fields().forEach { (k, v) -> if (k != "__name__") labels[k] = v.asText() }
            Sentry.metrics().gauge(q.name, value, q.unit, SentryMetricsParameters.create(labels))
            sent++
        }
        return sent
    }
}
