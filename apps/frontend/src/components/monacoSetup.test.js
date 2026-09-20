/**
 * Monaco setup regression tests (production incident, Sept 2026).
 *
 * Production kept every coding editor stuck on "Loading…" because
 * @monaco-editor/react fell back to its jsDelivr CDN default: the deployed
 * LAN cannot reach the internet. These tests pin the fix:
 *
 *   1. the loader is configured with a LOCAL monaco instance (no `paths`
 *      config — `paths.vs` is exactly what a CDN configuration looks like),
 *   2. a MonacoEnvironment worker getter exists and routes languages to
 *      real worker constructors (core editor worker for the assessment's
 *      python/c/cpp/java languages),
 *   3. importing the setup twice never reconfigures the loader (it is a
 *      one-time side effect, safe to import from anywhere).
 *
 * Every monaco module is mocked so the suite never loads the real editor
 * into jsdom — we assert the WIRING, not Monaco itself.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const loaderConfig = vi.fn();

vi.mock('@monaco-editor/react', () => ({
  loader: { config: loaderConfig },
}));

vi.mock('monaco-editor/esm/vs/editor/editor.api', () => ({
  editor: { create: vi.fn() },
  languages: { register: vi.fn() },
  Uri: { parse: vi.fn() },
  KeyMod: {},
  KeyCode: {},
}));

vi.mock('monaco-editor/esm/vs/basic-languages/python/python.contribution.js', () => ({}));
vi.mock('monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution.js', () => ({}));
vi.mock('monaco-editor/esm/vs/basic-languages/java/java.contribution.js', () => ({}));

class FakeWorker {}
vi.mock('monaco-editor/esm/vs/editor/editor.worker?worker', () => ({ default: FakeWorker }));
vi.mock('monaco-editor/esm/vs/language/json/json.worker?worker', () => ({ default: class {} }));
vi.mock('monaco-editor/esm/vs/language/css/css.worker?worker', () => ({ default: class {} }));
vi.mock('monaco-editor/esm/vs/language/html/html.worker?worker', () => ({ default: class {} }));
vi.mock('monaco-editor/esm/vs/language/typescript/ts.worker?worker', () => ({ default: class {} }));

describe('monacoSetup — local bundling, no CDN', () => {
  beforeEach(() => {
    vi.resetModules();
    loaderConfig.mockClear();
    delete self.MonacoEnvironment;
  });

  it('configures @monaco-editor/react with a local monaco instance and NO CDN paths', async () => {
    await import('./monacoSetup');

    expect(loaderConfig).toHaveBeenCalledTimes(1);
    const config = loaderConfig.mock.calls[0][0];

    // A local monaco namespace object was handed to the loader…
    expect(config).toHaveProperty('monaco');
    expect(config.monaco).toHaveProperty('editor');
    expect(config.monaco).toHaveProperty('languages');

    // …and no CDN/AMD `paths` config exists — `paths.vs` is exactly how
    // @monaco-editor/loader is pointed at the jsDelivr CDN that production
    // could not reach.
    expect(config.paths).toBeUndefined();
  });

  it('installs a MonacoEnvironment worker getter covering the assessment languages', async () => {
    await import('./monacoSetup');

    expect(self.MonacoEnvironment).toBeDefined();
    expect(typeof self.MonacoEnvironment.getWorker).toBe('function');

    const getWorker = self.MonacoEnvironment.getWorker;
    // The languages the coding section actually uses all resolve to the core
    // editor worker (basic languages never need a language worker).
    expect(getWorker('editor', 'python')).toBeInstanceOf(FakeWorker);
    expect(getWorker('editor', 'c')).toBeInstanceOf(FakeWorker);
    expect(getWorker('editor', 'cpp')).toBeInstanceOf(FakeWorker);
    expect(getWorker('editor', 'java')).toBeInstanceOf(FakeWorker);
    expect(getWorker('editor', 'json')).not.toBeInstanceOf(FakeWorker); // routed to the json worker
    expect(getWorker('editor', 'typescript')).not.toBeInstanceOf(FakeWorker);
  });
});
