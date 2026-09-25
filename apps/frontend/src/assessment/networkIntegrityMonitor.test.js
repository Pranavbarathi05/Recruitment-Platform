import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  createNetworkIntegrityMonitor,
  resolveNetworkMonitorUrl,
  isConfirmedConnectivity,
  DEFAULT_NETWORK_MONITOR_URL,
  NETWORK_MONITOR_INTERVAL_MS,
  NETWORK_VIOLATION_REASON,
} from './networkIntegrityMonitor';

/** A helper reply as the DEV helper actually sends it. */
const CONFIRMED = { target: '8.8.8.8', reachable: true, packetLoss: 0, rttMs: 12.4 };
const NO_REPLY = { target: '8.8.8.8', reachable: false, packetLoss: 100, rttMs: null };

function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body };
}

function countingFetch(responses) {
  let index = 0;
  const impl = vi.fn(async () => {
    const next = responses[Math.min(index, responses.length - 1)];
    index += 1;
    if (next instanceof Error) throw next;
    return next;
  });
  return impl;
}

function build({ fetchImpl, onViolation = vi.fn(), onError = vi.fn(), intervalMs = 60_000 } = {}) {
  const monitor = createNetworkIntegrityMonitor({
    attemptId: 'attempt-1',
    url: DEFAULT_NETWORK_MONITOR_URL,
    intervalMs,
    fetchImpl,
    onViolation,
    onError,
  });
  return { monitor, onViolation, onError };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function tick(ms) {
  await vi.advanceTimersByTimeAsync(ms);
}

describe('helper URL resolution', () => {
  it('defaults to loopback when nothing is configured', () => {
    expect(resolveNetworkMonitorUrl(undefined)).toBe(DEFAULT_NETWORK_MONITOR_URL);
    expect(resolveNetworkMonitorUrl({})).toBe(DEFAULT_NETWORK_MONITOR_URL);
  });

  it('honours an explicit VITE_NETWORK_MONITOR_URL', () => {
    expect(resolveNetworkMonitorUrl({ VITE_NETWORK_MONITOR_URL: 'http://127.0.0.1:9999' }))
      .toBe('http://127.0.0.1:9999');
  });
});

describe('reply interpretation', () => {
  it('accepts only a confirmed reply for the expected target', () => {
    expect(isConfirmedConnectivity(CONFIRMED)).toBe(true);
  });

  it('rejects malformed, non-boolean and wrong-target replies', () => {
    expect(isConfirmedConnectivity(null)).toBe(false);
    expect(isConfirmedConnectivity('<html>error</html>')).toBe(false);
    expect(isConfirmedConnectivity([])).toBe(false);
    expect(isConfirmedConnectivity({ target: '8.8.8.8', reachable: 'true' })).toBe(false);
    expect(isConfirmedConnectivity({ target: '8.8.8.8', reachable: 1 })).toBe(false);
    expect(isConfirmedConnectivity({ reachable: true })).toBe(false);
    // A rogue local service must not be able to fake a violation.
    expect(isConfirmedConnectivity({ target: '1.1.1.1', reachable: true })).toBe(false);
  });
});

describe('monitoring cadence', () => {
  it('does not probe immediately, and probes once per interval', async () => {
    const fetchImpl = countingFetch([jsonResponse(NO_REPLY)]);
    const { monitor } = build({ fetchImpl });

    monitor.start();
    expect(fetchImpl).not.toHaveBeenCalled();

    await tick(NETWORK_MONITOR_INTERVAL_MS - 1);
    expect(fetchImpl).not.toHaveBeenCalled();

    await tick(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    await tick(NETWORK_MONITOR_INTERVAL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(2);

    monitor.stop();
  });

  it('creates exactly one timer no matter how often start() is called', async () => {
    const fetchImpl = countingFetch([jsonResponse(NO_REPLY)]);
    const { monitor } = build({ fetchImpl });

    monitor.start();
    monitor.start();
    monitor.start();

    await tick(NETWORK_MONITOR_INTERVAL_MS);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    monitor.stop();
  });

  it('calls the loopback helper endpoint with no credentials and no cache', async () => {
    const fetchImpl = countingFetch([jsonResponse(NO_REPLY)]);
    const { monitor } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS);

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:8765/network-check');
    expect(init.credentials).toBe('omit');
    expect(init.cache).toBe('no-store');
    monitor.stop();
  });

  it('never overlaps probes when a check is slow', async () => {
    let resolveProbe;
    const fetchImpl = vi.fn(() => new Promise((resolve) => { resolveProbe = resolve; }));
    const { monitor } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    await tick(NETWORK_MONITOR_INTERVAL_MS);
    await tick(NETWORK_MONITOR_INTERVAL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(1); // still the same in-flight probe

    resolveProbe(jsonResponse(CONFIRMED));
    await tick(0);
    monitor.stop();
  });

  it('stop() clears the timer and is idempotent', async () => {
    const fetchImpl = countingFetch([jsonResponse(NO_REPLY)]);
    const { monitor } = build({ fetchImpl });

    monitor.start();
    monitor.stop();
    monitor.stop();
    monitor.stop();

    await tick(NETWORK_MONITOR_INTERVAL_MS * 3);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(monitor.isRunning()).toBe(false);
  });

  it('stop() aborts an in-flight probe', async () => {
    let signal;
    const fetchImpl = vi.fn((_url, init) => {
      signal = init.signal;
      return new Promise(() => {}); // never settles
    });
    const { monitor } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS);
    expect(signal.aborted).toBe(false);

    monitor.stop();
    expect(signal.aborted).toBe(true);
  });
});

describe('violation handling', () => {
  it('reports a confirmed connectivity exactly once and stops monitoring', async () => {
    const fetchImpl = countingFetch([jsonResponse(CONFIRMED)]);
    const { monitor, onViolation } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS);
    expect(onViolation).toHaveBeenCalledTimes(1);
    expect(onViolation).toHaveBeenCalledWith({
      attemptId: 'attempt-1',
      reason: NETWORK_VIOLATION_REASON,
    });
    expect(monitor.isRunning()).toBe(false);

    await tick(NETWORK_MONITOR_INTERVAL_MS * 5);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(onViolation).toHaveBeenCalledTimes(1);
  });

  it('keeps monitoring when the probe confirms nothing', async () => {
    const fetchImpl = countingFetch([jsonResponse(NO_REPLY), jsonResponse(NO_REPLY)]);
    const { monitor, onViolation, onError } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS * 2);

    expect(onViolation).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(monitor.isRunning()).toBe(true);
    monitor.stop();
  });

  it('continues when the helper is unavailable (non-2xx)', async () => {
    const fetchImpl = countingFetch([{ ok: false, status: 404, json: async () => ({}) }]);
    const { monitor, onViolation, onError } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS);

    expect(onViolation).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalled();
    expect(monitor.isRunning()).toBe(true);
    monitor.stop();
  });

  it('continues when the helper cannot be reached (connection refused)', async () => {
    const fetchImpl = vi.fn(async () => { throw new TypeError('Failed to fetch'); });
    const { monitor, onViolation, onError } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS);

    expect(onViolation).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalled();
    expect(monitor.isRunning()).toBe(true);
    monitor.stop();
  });

  it('continues when the helper returns a malformed body', async () => {
    const fetchImpl = countingFetch([
      { ok: true, status: 200, json: async () => { throw new Error('not json'); } },
    ]);
    const { monitor, onViolation, onError } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS);

    expect(onViolation).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalled();
    expect(monitor.isRunning()).toBe(true);
    monitor.stop();
  });

  it('treats an aborted (timed-out) probe as no violation, without an error report', async () => {
    const fetchImpl = vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => {
        const err = new Error('aborted');
        err.name = 'AbortError';
        reject(err);
      });
    }));
    const { monitor, onViolation, onError } = build({ fetchImpl });

    monitor.start();
    await tick(NETWORK_MONITOR_INTERVAL_MS);
    await tick(10_000); // request timeout fires

    expect(onViolation).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    monitor.stop();
  });
});
