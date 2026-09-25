# Network Monitor Agent (DEV-only client helper)

Optional companion process for the assessment **network-integrity monitor**.

## Why it exists

A browser cannot send ICMP echo requests, and `fetch("https://8.8.8.8")` is *not*
a ping — it is an HTTP request to a different protocol and port, and says
nothing about ICMP reachability. The assessment policy needs to know whether the
**candidate machine** can reach a fixed target over ICMP, so this small local
helper performs the real `ping` and answers over loopback HTTP:

```
assessment page (browser)
    -> GET http://127.0.0.1:8765/network-check     (loopback HTTP, CORS-restricted)
this helper
    -> ICMP echo request to 8.8.8.8                (system ping binary, fixed argv)
```

It is deliberately **not** part of the deployed stack: no Docker, no gateway or
Traefik change, nothing to deploy server-side.

## Design guarantees

| Guarantee | How |
|---|---|
| Never reachable from the network | binds `127.0.0.1` only (`build_server` refuses other hosts) |
| Cannot probe arbitrary hosts | target is the hardcoded constant `8.8.8.8`; the endpoint takes **no parameters** |
| No shell execution | fixed argv, no `shell=True`, no interpolation — there is no "run command" API |
| Only one operation | `GET /network-check`; everything else is 404/405 |
| One probe per window | overlapping requests share one in-flight probe (lock + 5s reuse) |
| Short-lived children | bounded timeout, child reaped, result cached for a few seconds |
| CORS restricted | explicit origin allowlist (defaults to the DEV Vite origins); never `*` |
| No privacy impact | it answers one question about one hardcoded IP; no traffic capture, no DNS history, no browsing data, no packet inspection |

## Run it (DEV)

```bash
# from the repository root
apps/backend/.venv/bin/python apps/network-monitor-agent/agent.py

# one-shot check (no server):
apps/backend/.venv/bin/python apps/network-monitor-agent/agent.py --once
```

Options: `--port` (default `8765`, or `NETWORK_MONITOR_PORT`), `--allow-origin`
(repeatable; defaults to `http://localhost:5173` and `http://127.0.0.1:5173`).

Point the frontend at a different port with `VITE_NETWORK_MONITOR_URL`
(see `apps/frontend/src/assessment/networkIntegrityMonitor.js`).

## Tests

```bash
cd apps/network-monitor-agent
../backend/.venv/bin/python -m pytest test_agent.py -q
```

The tests mock the ping binary; they never send real ICMP traffic.

## How the assessment uses it

Monitoring is **off unless an admin enables it** (`assessment_config.network_integrity_monitoring`,
default `false`). When enabled, the policy is frozen into the plan snapshot of
each new attempt, so changing the setting never affects an attempt that is
already running. The candidate workspace then checks this helper once per minute
while the attempt is active; a **confirmed** reply (`reachable === true` for
`8.8.8.8`) finalises the attempt through the existing authoritative submit path
with the reason `network_integrity_violation`. Any failure to reach the helper —
down, slow, malformed, or no reply — never terminates an assessment.
