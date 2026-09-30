#!/usr/bin/env python3
"""Create/update the two Sentry dashboards (idempotent: matched by title).

Token: ~/.sentry-alerts-token (scope org:write; never printed).
Usage: python3 dashboards.py [--dry-run]
"""
import json
import os
import sys
import urllib.request

ORG = "crytoworld"
API = f"https://us.sentry.io/api/0/organizations/{ORG}/dashboards/"
APP_PROJECT = 4512175618326528       # web3j-rpc-logger
PLATFORM_PROJECT = 4512176378544128  # platform-k8s


# ---- widget helpers ---------------------------------------------------------
def m(agg, name, mtype, unit="none"):
    """Application-metric aggregate, e.g. avg(value,jvm.memory.used,gauge,byte)."""
    return f"{agg}(value,{name},{mtype},{unit})"


def widget(title, display, wtype, aggregates, x, y, w, h,
           columns=(), conditions="", orderby=None, limit=None, description=""):
    columns = list(columns)
    q = {
        "name": "",
        "aggregates": aggregates,
        "columns": columns,
        "fields": columns + aggregates,
        "conditions": conditions,
        "orderby": orderby if orderby is not None else (f"-{aggregates[0]}" if columns else ""),
        "fieldAliases": [],
    }
    wd = {
        "title": title,
        "description": description,
        "displayType": display,
        "widgetType": wtype,
        "interval": "5m",
        "queries": [q],
        "layout": {"x": x, "y": y, "w": w, "h": h, "minH": 1},
    }
    if limit or columns:
        wd["limit"] = limit or 10
    return wd


def big(title, wtype, agg, x, y, conditions="", description=""):
    return widget(title, "big_number", wtype, [agg], x, y, 1, 1,
                  conditions=conditions, description=description)


TM, SPANS, LOGS, ERRORS = "tracemetrics", "spans", "logs", "error-events"


# ---- dashboard 1: the application ------------------------------------------
app = {
    "title": "web3j-rpc-logger - Application",
    "projects": [APP_PROJECT],
    "period": "24h",
    "widgets": [
        # row 0: headline numbers
        big("Latest block", TM, m("max", "eth.block.number", "gauge"), 0, 0),
        big("Avg txs / block", TM, m("avg", "eth.block.transactions", "gauge"), 1, 0),
        big("RPC polls", TM, m("sum", "rpc.poll.count", "counter"), 2, 0),
        big("RPC failures", TM, m("sum", "rpc.error.count", "counter"), 3, 0),
        big("Errors (issues)", ERRORS, "count()", 4, 0),
        big("p95 poll time", SPANS, "p95(span.duration)", 5, 0, conditions="span.op:rpc.poll"),
        # row 1: block contents
        widget("Transactions per block (avg / max)", "line", TM,
               [m("avg", "eth.block.transactions", "gauge"), m("max", "eth.block.transactions", "gauge")],
               0, 1, 3, 2),
        widget("Gas utilization % of block limit", "line", TM,
               [m("avg", "eth.block.gas_utilization", "gauge", "percent"),
                m("max", "eth.block.gas_utilization", "gauge", "percent")], 3, 1, 3, 2),
        # row 2: RPC performance
        widget("Poll duration p50 / p95 / max", "line", SPANS,
               ["p50(span.duration)", "p95(span.duration)", "max(span.duration)"], 0, 3, 3, 2,
               conditions="span.op:rpc.poll"),
        widget("RPC HTTP call p95 by endpoint", "line", SPANS, ["p95(span.duration)"], 3, 3, 3, 2,
               columns=["span.description"], conditions="span.op:http.client", limit=5),
        # row 3: reliability
        widget("Polls vs failures", "bar", TM,
               [m("sum", "rpc.poll.count", "counter"), m("sum", "rpc.error.count", "counter")],
               0, 5, 3, 2),
        widget("Gas used per block (avg)", "line", TM, [m("avg", "eth.block.gas_used", "gauge")],
               3, 5, 3, 2),
        # row 4: logs + slowest operations
        widget("Logs by severity", "bar", LOGS, ["count(message)"], 0, 7, 3, 2,
               columns=["severity"], limit=5),
        widget("Slowest span operations", "table", SPANS,
               ["p95(span.duration)", "avg(span.duration)", "count()"], 3, 7, 3, 2,
               columns=["span.op", "span.description"], limit=10),
    ],
}

# ---- dashboard 2: cluster + JVM (prom-bridge) --------------------------------
by_pod = ["namespace", "pod"]
platform = {
    "title": "platform-k8s - Cluster & JVM",
    "projects": [PLATFORM_PROJECT],
    "period": "24h",
    "widgets": [
        # row 0: health at a glance
        big("Max memory % of limit", TM, m("max", "k8s.container.memory.utilization", "gauge", "percent"), 0, 0),
        big("OOM kills (window)", TM, m("sum", "k8s.container.oom_events", "gauge"), 1, 0),
        big("Container restarts", TM, m("sum", "k8s.container.restarts", "gauge"), 2, 0),
        big("Containers waiting", TM, m("max", "k8s.container.waiting", "gauge"), 3, 0,
            description="CrashLoopBackOff, ImagePullBackOff, ... (0 = healthy)"),
        big("Bridge query errors", TM, m("sum", "prom_bridge.query.errors", "counter"), 4, 0),
        big("Series forwarded / cycle", TM, m("avg", "prom_bridge.series.forwarded", "gauge"), 5, 0),
        # rows 1-3: containers (all namespaces)
        widget("CPU % by pod", "line", TM, [m("avg", "k8s.container.cpu.usage", "gauge", "percent")],
               0, 1, 3, 2, columns=by_pod),
        widget("Memory % of limit by pod", "line", TM,
               [m("max", "k8s.container.memory.utilization", "gauge", "percent")], 3, 1, 3, 2, columns=by_pod),
        widget("Memory working set by pod", "area", TM,
               [m("avg", "k8s.container.memory.working_set", "gauge", "byte")], 0, 3, 3, 2, columns=by_pod),
        widget("CPU throttling by pod (periods/s)", "line", TM,
               [m("avg", "k8s.container.cpu.throttled", "gauge")], 3, 3, 3, 2, columns=by_pod),
        widget("Network receive by pod (B/s)", "line", TM,
               [m("avg", "k8s.pod.network.receive_bytes_per_second", "gauge", "byte")], 0, 5, 3, 2, columns=by_pod),
        widget("Network transmit by pod (B/s)", "line", TM,
               [m("avg", "k8s.pod.network.transmit_bytes_per_second", "gauge", "byte")], 3, 5, 3, 2, columns=by_pod),
        # row 4: failures
        widget("Restarts by pod", "bar", TM, [m("sum", "k8s.container.restarts", "gauge")],
               0, 7, 2, 2, columns=by_pod),
        widget("OOM kills by pod", "bar", TM, [m("sum", "k8s.container.oom_events", "gauge")],
               2, 7, 2, 2, columns=by_pod),
        widget("Waiting containers by reason", "bar", TM, [m("max", "k8s.container.waiting", "gauge")],
               4, 7, 2, 2, columns=["namespace", "pod", "reason"]),
        # rows 5-6: JVM runtime (every app via Sentry agent)
        widget("JVM memory used by pod (heap / non-heap)", "area", TM,
               [m("avg", "jvm.memory.used", "gauge", "byte")], 0, 9, 3, 2,
               columns=["namespace", "pod", "jvm_memory_type"]),
        widget("JVM CPU % by pod", "line", TM, [m("avg", "jvm.cpu.utilization", "gauge", "percent")],
               3, 9, 3, 2, columns=by_pod),
        widget("JVM GC time ratio by collector", "line", TM, [m("avg", "jvm.gc.time_ratio", "gauge", "ratio")],
               0, 11, 3, 2, columns=["namespace", "pod", "jvm_gc_name"]),
        widget("JVM threads by pod", "line", TM, [m("avg", "jvm.threads", "gauge")],
               3, 11, 3, 2, columns=by_pod),
        # row 7: current top consumers
        widget("Top containers by memory % of limit", "table", TM,
               [m("max", "k8s.container.memory.utilization", "gauge", "percent"),
                m("max", "k8s.container.memory.working_set", "gauge", "byte"),
                m("max", "k8s.container.cpu.usage", "gauge", "percent")],
               0, 13, 6, 2, columns=["namespace", "pod", "container"], limit=15),
    ],
}


# ---- create or update -----------------------------------------------------------
def call(method, url, token, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read() or b"null")


def main():
    dashboards = [app, platform]
    if "--dry-run" in sys.argv:
        for d in dashboards:
            print(f"{d['title']}: {len(d['widgets'])} widgets")
        print(json.dumps(dashboards[1]["widgets"][6], indent=1))
        return
    with open(os.path.expanduser("~/.sentry-alerts-token")) as f:
        token = f.read().strip()
    _, existing = call("GET", API + "?per_page=100", token)
    ids = {d["title"]: d["id"] for d in existing}
    for d in dashboards:
        try:
            if d["title"] in ids:
                status, res = call("PUT", f"{API}{ids[d['title']]}/", token, d)
            else:
                status, res = call("POST", API, token, d)
            print(f"{status} {d['title']} -> https://{ORG}.sentry.io/dashboard/{res['id']}/")
        except urllib.error.HTTPError as e:
            print(f"FAILED {d['title']}: HTTP {e.code} {e.read().decode()[:800]}")


if __name__ == "__main__":
    main()
