package rpclogger

import io.sentry.Sentry
import io.sentry.SpanStatus
import io.sentry.TransactionOptions
import org.web3j.protocol.Web3j
import org.web3j.protocol.core.DefaultBlockParameter
import org.web3j.protocol.core.Response
import org.web3j.protocol.http.HttpService
import java.math.BigInteger

// Sentry is initialised by the Sentry Java agent (injected by the sentry-agent-init
// container, configured via SENTRY_* env and sentry.properties). The agent also traces
// each web3j HTTP call (OkHttp) and exports JVM runtime metrics for Prometheus.
// This file only adds what the agent cannot know: the poll transaction and eth.* data.
fun main() {
    val rpcUrl = System.getenv("RPC_URL") ?: "https://ethereum.publicnode.com"
    val pollMs = System.getenv("POLL_INTERVAL")?.toLongOrNull() ?: 10_000L

    val poller = BlockPoller(Web3j.build(HttpService(rpcUrl)))
    Log.info("Starting web3j-rpc-logger | RPC: $rpcUrl | poll: ${pollMs}ms")
    while (true) {
        poller.poll()
        Thread.sleep(pollMs)
    }
}

/** One poll = one Sentry transaction. A background loop has no incoming request to hang a
 *  trace on, so the root is created here; the agent's HTTP spans nest under it. */
class BlockPoller(private val web3j: Web3j) {
    private var lastBlock: BigInteger? = null

    fun poll() {
        val tx = Sentry.startTransaction("rpc.poll", "rpc.poll", TransactionOptions().apply { isBindToScope = true })
        try {
            Sentry.metrics().count("rpc.poll.count")

            val number = web3j.ethBlockNumber().send().orThrow().blockNumber
            Sentry.metrics().gauge("eth.block.number", number.toDouble())

            if (number == lastBlock) {
                Log.debug("No new block (still $number)")
            } else {
                lastBlock = number
                val block = web3j.ethGetBlockByNumber(DefaultBlockParameter.valueOf(number), false).send().orThrow().block
                    ?: error("Block $number not found")
                val txCount = block.transactions.size
                Sentry.metrics().gauge("eth.block.transactions", txCount.toDouble())
                Sentry.metrics().gauge("eth.block.gas_used", block.gasUsed.toDouble())
                Sentry.metrics().gauge("eth.block.gas_utilization",
                    block.gasUsed.toDouble() * 100 / block.gasLimit.toDouble(), "percent")
                Log.info("New block $number txs=$txCount gas_used=${block.gasUsed} miner=${block.miner}")
            }
            tx.status = SpanStatus.OK
        } catch (e: Exception) {
            tx.throwable = e
            tx.status = SpanStatus.INTERNAL_ERROR
            Sentry.captureException(e)
            Sentry.metrics().count("rpc.error.count")
            Log.error("RPC poll failed: ${e.message}")
        } finally {
            tx.finish()
        }
    }
}

private fun <R : Response<*>> R.orThrow(): R = also {
    if (hasError()) error("RPC error ${error.code}: ${error.message}")
}
