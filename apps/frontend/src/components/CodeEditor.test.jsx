/**
 * CodeEditor Monaco bootstrapping tests.
 *
 * Production incident (Sept 2026): every coding editor stayed on "Loading…"
 * because @monaco-editor/react fell back to its jsDelivr CDN default, which the
 * deployed LAN cannot reach. Two properties must hold:
 *
 *   1. the editor is NOT mounted until the local Monaco setup has been applied
 *      (mounting first lets the loader fall back to the CDN and hang),
 *   2. the setup module is imported lazily and exactly once, shared by every
 *      editor instance, so the ~3.5 MB Monaco bundle is not part of the app's
 *      initial download.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

const setupLoads = { count: 0 };

vi.mock('@monaco-editor/react', () => ({
  loader: { config: vi.fn() },
  default: ({ language }) => <div data-testid="monaco-editor">monaco:{language}</div>,
}));

// The real setup module pulls in the whole Monaco ESM build, which is
// browser-only, so the test substitutes a module that records its load. The
// import inside CodeEditor stays dynamic, which is what the lazy gate depends on.
vi.mock('./monacoSetup', () => {
  setupLoads.count += 1;
  return { monaco: { editor: {}, languages: {} } };
});

beforeEach(() => {
  cleanup();
});

describe('CodeEditor — lazy local Monaco bootstrap', () => {
  it('gates the editor on the local Monaco setup and imports it only once', async () => {
    const { default: CodeEditor } = await import('./CodeEditor');

    // Nothing is rendered until the local setup resolves.
    render(<CodeEditor language="c" value="int add(int a, int b) {}" />);
    const editor = await screen.findByTestId('monaco-editor');

    // The editor receives the language it was given — C included.
    expect(editor).toHaveTextContent('monaco:c');
    // The local setup module was loaded (loader.config ran) exactly once.
    expect(setupLoads.count).toBe(1);

    // A second editor (e.g. switching problems) reuses the same memoized load.
    cleanup();
    render(<CodeEditor language="java" value="" />);
    expect(await screen.findByTestId('monaco-editor')).toHaveTextContent('monaco:java');
    expect(setupLoads.count).toBe(1);
  });
});
