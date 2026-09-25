/**
 * Optional assessment network-integrity monitor.
 *
 * WHAT IT DOES
 * While — and ONLY while — an attempt that was created with the
 * `network_integrity_monitoring` policy is active, this monitor asks the
 * candidate machine's local helper (see apps/network-monitor-agent) whether
 * that machine can reach the fixed ICMP target. A CONFIRMED successful ICMP
 * reply is the only thing that counts as a violation; it is reported exactly
 * once, and the caller finalises the attempt through the existing authoritative
 * submit path.
 *
 * WHY A LOCAL HELPER
 * A browser cannot send ICMP echo requests, and `fetch("https://8.8.8.8")` is
 * NOT an ICMP ping (it is an HTTP request to a different protocol/port and says
 * nothing about ICMP reachability). The helper is the smallest mechanism that
 * performs the actual ping:
 *
 *     assessment page -> GET http://127.0.0.1:<port>/network-check -> ICMP
 *
 * It binds loopback only and probes a hardcoded target, so the browser can
 * never make it probe anything else.
 *
 * FAILURE POLICY (deliberate)
 * A missing/unreachable helper, a malformed reply, a timeout, packet loss, or
 * any error is NEVER treated as a violation — the assessment simply continues.
 * Only `reachable === true` for the expected target terminates the attempt.
 */

/** Default helper endpoint (loopback only). Override with VITE_NETWORK_MONITOR_URL. */
export const DEFAULT_NETWORK_MONITOR_URL = 'http://127.0.0.1:8765';

/** The ONE target the helper is allowed to probe. */
export const NETWORK_MONITOR_TARGET = '8.8.8.8';

/**
 * How often the candidate machine is checked. The first check happens after
 * one full interval (start -> wait -> check -> wait -> check), never as an
 * immediate burst: exactly one timer, one probe per interval.
 */
export const NETWORK_MONITOR_INTERVAL_MS = 60_000;

/** Abort a hanging helper request rather than letting it pile up. */
export const NETWORK_MONITOR_REQUEST_TIMEOUT_MS = 10_000;

/** The single allowlisted termination reason this monitor can report. */
export const NETWORK_VIOLATION_REASON = 'network_integrity_violation';

/** Candidate-facing wording. Deliberately free of implementation detail. */
export const NETWORK_VIOLATION_MESSAGE =
  'Assessment terminated: unauthorized internet connectivity was detected.';

/** Resolve the helper URL from the environment, falling back to loopback. */
export function resolveNetworkMonitorUrl(env = import.meta?.env) {
  const configured = env?.VITE_NETWORK_MONITOR_URL;
  if (typeof configured === 'string' && configured.trim()) return configured.trim();
  return DEFAULT_NETWORK_MONITOR_URL;
}

/**
 * Interpret a helper reply. Returns true ONLY for a confirmed success.
 *
 * Anything unexpected is "no connectivity confirmed", never a violation:
 *   - reply is not an object (HTML error page, empty body, plain text)
 *   - `reachable` is not strictly true ("true", 1, undefined all fail)
 *   - `target` is present but is not the expected address (a rogue service on
 *     the helper port must not be able to fake a violation)
 */
export function isConfirmedConnectivity(reply) {
  if (!reply || typeof reply !== 'object' || Array.isArray(reply)) return false;
  if (reply.reachable !== true) return false;
  if (reply.target !== NETWORK_MONITOR_TARGET) return false;
  return true;
}

/**
 * Create the monitor for one attempt.
 *
 * @param {object} options
 * @param {string} [options.attemptId]   Attempt this monitor is bound to.
 * @param {string} [options.url]         Helper base URL.
 * @param {number} [options.intervalMs]  Check interval.
 * @param {Function} [options.fetchImpl] Injected fetch (tests).
 * @param {Function} [options.onViolation] Called at most ONCE on confirmed connectivity.
 * @param {Function} [options.onError]   Called on any non-fatal monitoring error.
 * @returns {{start: Function, stop: Function, checkNow: Function, isRunning: Function}}
 */
export function createNetworkIntegrityMonitor({
  attemptId = null,
  url = DEFAULT_NETWORK_MONITOR_URL,
  intervalMs = NETWORK_MONITOR_INTERVAL_MS,
  requestTimeoutMs = NETWORK_MONITOR_REQUEST_TIMEOUT_MS,
  fetchImpl = typeof fetch === 'function' ? fetch : null,
  onViolation = () => {},
  onError = () => {},
} = {}) {
  let intervalId = null;
  let controller = null;
  let stopped = false;
  let violationReported = false;
  let checking = false;

  function isRunning() {
    return intervalId !== null;
  }

  function stop() {
    stopped = true;
    if (intervalId !== null) {
      clearInterval(intervalId);
      intervalId = null;
    }
    if (controller) {
      // Cancel an in-flight probe so nothing survives an unmount.
      try {
        controller.abort();
      } catch {
        /* already settled */
      }
      controller = null;
    }
  }

  function reportViolation() {
    if (violationReported) return;
    violationReported = true;
    // Stop FIRST: exactly one timer, one report, no further probes — the
    // submission that follows cannot be raced by this monitor.
    stop();
    onViolation({ attemptId, reason: NETWORK_VIOLATION_REASON });
  }

  async function checkNow() {
    if (stopped || violationReported || !fetchImpl) return false;
    if (checking) return false; // never overlap probes
    checking = true;
    controller = typeof AbortController === 'function' ? new AbortController() : null;
    const timeout = controller
      ? setTimeout(() => {
          try {
            controller.abort();
          } catch {
            /* already settled */
          }
        }, requestTimeoutMs)
      : null;
    try {
      const resp = await fetchImpl(`${url}/network-check`, {
        method: 'GET',
        credentials: 'omit',
        cache: 'no-store',
        signal: controller ? controller.signal : undefined,
      });
      if (!resp || !resp.ok) {
        // Helper down / wrong port / non-2xx: not a violation.
        onError('network monitor helper unavailable');
        return false;
      }
      let body = null;
      try {
        body = await resp.json();
      } catch {
        onError('network monitor returned a malformed response');
        return false;
      }
      if (isConfirmedConnectivity(body)) {
        reportViolation();
        return true;
      }
      return false;
    } catch (err) {
      // Abort, network refusal, DNS/loopback error — all "no confirmed
      // connectivity". Never punish the candidate for infrastructure failure.
      if (!(err && err.name === 'AbortError')) {
        onError('network monitor check failed');
      }
      return false;
    } finally {
      if (timeout !== null) clearTimeout(timeout);
      controller = null;
      checking = false;
    }
  }

  function start() {
    if (stopped || isRunning() || violationReported) return; // idempotent: no duplicate timers
    intervalId = setInterval(() => {
      checkNow();
    }, intervalMs);
  }

  return { start, stop, checkNow, isRunning };
}
