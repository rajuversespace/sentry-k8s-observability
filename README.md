# sentry-k8s-observability

Traces, errors, profiles, logs and metrics for JVM apps on Kubernetes, all in
[Sentry](https://sentry.io), with **no observability code in the apps**.

- Every app gets the Sentry Java agent through an **init container**.
- One shared **platform** namespace (Prometheus, kube-state-metrics and a small
  bridge) forwards cluster and JVM metrics to Sentry.

Tested on k3d (k3s v1.35, arm64) with Sentry SDK/agent 8.58.0.

```
 ┌─ namespace <app> (one per app) ────────────────────────────────┐
 │  initContainer sentry-agent-init  ──copies agent──► emptyDir   │
 │  app container (plain JVM image)                                │
 │    JAVA_TOOL_OPTIONS=-javaagent:/sentry/...agent.jar            │
 │    Secret sentry (DSN) + ConfigMap sentry.properties            │
 │    :9464/metrics (JVM runtime metrics, OpenTelemetry)           │
 └──────┬───────────────────────────────────┬─────────────────────┘
        │ traces, errors, profiles,          │ scraped
        │ app logs/metrics (Sentry API)      ▼
        │                      ┌─ namespace platform ──────────────────────┐
        │                      │ Prometheus ◄─ kubelet cAdvisor (:10250)   │
        │                      │            ◄─ kube-state-metrics          │
        │                      │            ◄─ app pods :9464              │
        │                      │ prom-bridge ─ PromQL every 15s            │
        │                      └──────────────┬────────────────────────────┘
        ▼                                     ▼
  Sentry project <app>                 Sentry project platform-k8s
```

## What each piece does

| Path | What it is |
|---|---|
| `images/sentry-agent-init/` | Init image: the Sentry Java agent with async-profiler **merged into the same jar**, so profiling works through a single `-javaagent` flag. Downloads are checksum-pinned. |
| `k8s/apps/_template/app.yaml` | The per-app template (namespace, `sentry.properties`, Deployment with the init container). Copy it for each app. |
| `k8s/apps/web3j-rpc-logger/` | Example app: polls an Ethereum RPC node (web3j). |
| `apps/web3j-rpc-logger/` | Example app source. It also contains `PromBridge.kt`, the Prometheus → Sentry Metrics bridge. |
| `k8s/platform/` | Prometheus (least-privilege RBAC: `nodes/metrics`, **not** `nodes/proxy`), kube-state-metrics (pods only), and prom-bridge with its PromQL query list. |
| `sentry/dashboards.py` | Creates or updates two Sentry dashboards (app, and cluster + JVM) through the Sentry API. |

## Why a bridge?

As of 2026, Sentry accepts OTLP **traces and logs** but not OTLP metrics or Prometheus
remote-write ([getsentry/sentry#111136](https://github.com/getsentry/sentry/issues/111136)).
`prom-bridge` runs each PromQL query in its ConfigMap every 15s and sends each
resulting series to Sentry Application Metrics as a gauge, keeping the Prometheus labels as
attributes. If Sentry ships OTLP metrics, replace the bridge with an OpenTelemetry Collector.

## Setup

Prerequisites: a k3d/Kubernetes cluster, Docker, and two Sentry projects (one for the app,
e.g. `web3j-rpc-logger`, and `platform-k8s`). **DSNs are never committed.** They go into
Kubernetes Secrets at deploy time.

```bash
# 1. Images
docker build -t sentry-agent-init:8.58.0 images/sentry-agent-init
docker build -t web3j-rpc-logger:v9 apps/web3j-rpc-logger
k3d image import sentry-agent-init:8.58.0 web3j-rpc-logger:v9 -c <cluster>

# 2. Platform
kubectl apply -f k8s/platform/namespace.yaml
kubectl -n platform create secret generic sentry --from-literal=dsn='<platform-k8s DSN>'
kubectl apply -f k8s/platform/

# 3. App
kubectl apply -f k8s/apps/web3j-rpc-logger/app.yaml
kubectl -n web3j-rpc-logger create secret generic sentry --from-literal=dsn='<app DSN>'
kubectl -n web3j-rpc-logger rollout restart deploy/web3j-rpc-logger
```

## Add an app

1. Create a Sentry project `<app>` (platform: java) and copy its DSN.
2. `cp -r k8s/apps/_template k8s/apps/<app>` and replace `APP_NAME`, `IMAGE` and `IMAGE_TAG`.
3. `kubectl apply -f k8s/apps/<app>/app.yaml`
4. `kubectl -n <app> create secret generic sentry --from-literal=dsn='<DSN>'`
5. Restart the deployment.

The app then gets traces (HTTP, JDBC, …), errors, continuous profiling, release tagging and
JVM metrics without any code changes. For custom logs or metrics, add
`compileOnly("io.sentry:sentry:8.58.0")` and call `Sentry.logger()` / `Sentry.metrics()`.
Keep that version equal to the `sentry-agent-init` tag.

## Dashboards

```bash
# Token with org:write, kept in a file (never in the repo or the shell history)
echo '<token>' > ~/.sentry-alerts-token && chmod 600 ~/.sentry-alerts-token
python3 sentry/dashboards.py --dry-run   # inspect
python3 sentry/dashboards.py             # create/update (matched by title)
```

Before running it, edit `ORG`, `APP_PROJECT` and `PLATFORM_PROJECT` at the top of the script
to match your org slug and project IDs.

## Known trade-offs

- **Memory:** the agent adds about 100 MB of memory per JVM. Size limits accordingly.
- **Cost:** Sentry Application Metrics are billed per GB of raw events. The bridge's
  cluster-wide queries (every namespace) dominate the volume; add `namespace="…"` filters in
  `k8s/platform/prom-bridge.yaml` to reduce it.
- **Trace linking:** JVM metrics forwarded by the bridge aren't tied to traces, since they
  arrive through Prometheus rather than the SDK.
