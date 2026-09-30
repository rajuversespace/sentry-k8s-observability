package rpclogger

import io.sentry.Sentry
import io.sentry.metrics.SentryMetricsParameters
import org.slf4j.LoggerFactory

/** Writes each log line to stdout (kubectl logs) and to Sentry Logs. */
object Log {
    private val console = LoggerFactory.getLogger("rpc-logger")

    fun debug(msg: String) { console.debug(msg); Sentry.logger().debug("%s", msg) }
    fun info(msg: String) { console.info(msg); Sentry.logger().info("%s", msg) }
    fun warn(msg: String) { console.warn(msg); Sentry.logger().warn("%s", msg) }
    fun error(msg: String) { console.error(msg); Sentry.logger().error("%s", msg) }
}

fun attrs(vararg pairs: Pair<String, Any>): SentryMetricsParameters =
    SentryMetricsParameters.create(mapOf(*pairs))
