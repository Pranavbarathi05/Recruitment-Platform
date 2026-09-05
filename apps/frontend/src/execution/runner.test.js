import { describe, it, expect, vi, afterEach } from 'vitest';
import { WorkerRunner } from './runner';

/** Minimal stand-in for a Web Worker (message + error events, terminate). */
class FakeWorker {
  constructor() {
    this.listeners = { message: [], error: [] };
    this.posted = [];
    this.terminated = false;
    this.onMessageReceived = null;
  }

  addEventListener(type, cb) {
    this.listeners[type].push(cb);
  }

  postMessage(msg) {
    this.posted.push(msg);
    if (this.onMessageReceived) this.onMessageReceived(msg, this);
  }

  terminate() {
    this.terminated = true;
  }

  emitMessage(data) {
    this.listeners.message.forEach((cb) => cb({ data }));
  }

  emitError(err) {
    this.listeners.error.forEach((cb) => cb(err));
  }
}

const SAMPLE_REQUEST = {
  language: 'python3',
  sourceCode: 'def solve(n):\n    return n * n',
  testCases: [{ id: 't1', arguments: [2], expected_output: 4 }],
  functionName: 'solve',
  className: null,
  timeLimitMs: 2000,
};

/** Worker that answers loading -> started -> result asynchronously. */
function respondingWorkerFactory({ resultFactory, workerHook } = {}) {
  return () => {
    const worker = new FakeWorker();
    worker.onMessageReceived = (msg) => {
      if (workerHook) workerHook(msg, worker);
      if (msg.type !== 'execute') return;
      worker.emitMessage({ type: 'loading', runId: msg.runId });
      setTimeout(() => {
        worker.emitMessage({ type: 'started', runId: msg.runId });
        setTimeout(() => {
          const result = resultFactory
            ? resultFactory(msg.payload)
            : { all_passed: true, results: [] };
          worker.emitMessage({ type: 'result', runId: msg.runId, result });
        }, 0);
      }, 0);
    };
    return worker;
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('WorkerRunner', () => {
  it('executes locally through the worker and resolves with the result', async () => {
    let worker;
    const runner = new WorkerRunner(
      respondingWorkerFactory({ workerHook: (_msg, w) => { worker = w; } })
    );

    const result = await runner.run(SAMPLE_REQUEST);

    expect(result.all_passed).toBe(true);
    expect(worker.posted.length).toBe(1);
    expect(worker.posted[0].type).toBe('execute');
    expect(worker.posted[0].runId).toBe(1);
    expect(worker.posted[0].payload.sourceCode).toBe(SAMPLE_REQUEST.sourceCode);
    expect(worker.posted[0].payload.testCases).toEqual(SAMPLE_REQUEST.testCases);
  });

  it('rejects languages without a client-side runtime without spawning a worker', async () => {
    const factory = vi.fn(respondingWorkerFactory());
    const runner = new WorkerRunner(factory);
    await expect(
      runner.run({ ...SAMPLE_REQUEST, language: 'cpp' })
    ).rejects.toThrow('no client-side runtime');
    expect(factory).not.toHaveBeenCalled();
  });

  it('ignores stale results from a previous run id', async () => {
    const worker = new FakeWorker();
    const runner = new WorkerRunner(() => worker);

    const promise = runner.run(SAMPLE_REQUEST);

    // A late/foreign result must not settle the pending run.
    worker.emitMessage({ type: 'result', runId: 999, result: { all_passed: true, stale: true } });
    expect(runner.busy).toBe(true);

    worker.emitMessage({ type: 'started', runId: 1 });
    worker.emitMessage({ type: 'result', runId: 1, result: { all_passed: true, results: [], fresh: true } });

    const result = await promise;
    expect(result.stale).toBeUndefined();
    expect(result.fresh).toBe(true);
    expect(runner.busy).toBe(false);
  });

  it('terminates the worker on timeout and reports TLE', async () => {
    vi.useFakeTimers();
    const factory = vi.fn(() => {
      const worker = new FakeWorker();
      worker.onMessageReceived = (msg) => {
        if (msg.type === 'execute') {
          worker.emitMessage({ type: 'loading', runId: msg.runId });
          worker.emitMessage({ type: 'started', runId: msg.runId });
          // Never answers: simulates an infinite loop blocking the worker.
        }
      };
      return worker;
    });

    const runner = new WorkerRunner(factory);
    const promise = runner.run({ ...SAMPLE_REQUEST, timeLimitMs: 500 });
    const firstWorker = factory.mock.results[0].value;

    await vi.advanceTimersByTimeAsync(500 + 1500);

    const result = await promise;
    expect(result.results[0].status).toBe('timeout');
    expect(result.results[0].execution_time_ms).toBe(500);
    expect(firstWorker.terminated).toBe(true);

    // Next run must recreate a fresh worker and work again.
    const secondPromise = runner.run({ ...SAMPLE_REQUEST, timeLimitMs: 500 });
    const secondWorker = factory.mock.results[1].value;
    // Respond synchronously so fake timers are not needed for this phase.
    secondWorker.onMessageReceived = (msg) => {
      if (msg.type === 'execute') {
        secondWorker.emitMessage({ type: 'loading', runId: msg.runId });
        secondWorker.emitMessage({ type: 'started', runId: msg.runId });
        secondWorker.emitMessage({
          type: 'result',
          runId: msg.runId,
          result: { all_passed: true, results: [] },
        });
      }
    };
    secondWorker.postMessage(secondWorker.posted[0] || { type: 'noop' });

    const secondResult = await secondPromise;
    expect(factory).toHaveBeenCalledTimes(2);
    expect(secondResult.all_passed).toBe(true);
    expect(secondWorker.terminated).toBe(false);
  });

  it('rejects overlapping executions', async () => {
    const runner = new WorkerRunner(respondingWorkerFactory());
    const first = runner.run(SAMPLE_REQUEST);
    await expect(runner.run(SAMPLE_REQUEST)).rejects.toThrow('already in progress');
    await first;
    expect(runner.busy).toBe(false);
  });

  it('supports multiple consecutive runs', async () => {
    const results = [
      { all_passed: true, results: [{ id: 't1', passed: true, status: 'passed' }] },
      { all_passed: false, results: [{ id: 't1', passed: false, status: 'failed' }] },
    ];
    let calls = 0;
    const runner = new WorkerRunner(
      respondingWorkerFactory({
        resultFactory: () => results[calls++ % results.length],
      })
    );

    const first = await runner.run(SAMPLE_REQUEST);
    const second = await runner.run(SAMPLE_REQUEST);

    expect(first.all_passed).toBe(true);
    expect(second.all_passed).toBe(false);
    expect(second.results[0].status).toBe('failed');
  });

  it('rejects with an error when the runtime fails to initialize', async () => {
    vi.useFakeTimers();
    const factory = vi.fn(() => new FakeWorker()); // never responds at all
    const runner = new WorkerRunner(factory);
    const promise = runner.run(SAMPLE_REQUEST);
    const worker = factory.mock.results[0].value;

    // Attach the rejection handler BEFORE the timer fires so the rejection is
    // never unhandled while fake timers advance.
    const expectation = expect(promise).rejects.toThrow('failed to initialize');
    await vi.advanceTimersByTimeAsync(60000);

    await expectation;
    expect(worker.terminated).toBe(true);
  });

  it('fails the run when the worker errors out', async () => {
    const worker = new FakeWorker();
    const runner = new WorkerRunner(() => worker);
    const promise = runner.run(SAMPLE_REQUEST);
    worker.emitError(new Error('worker blew up'));
    await expect(promise).rejects.toThrow('worker blew up');
  });
});