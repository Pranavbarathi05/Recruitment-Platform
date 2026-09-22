import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppShell } from './App';

vi.mock('./hooks/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: false, user: null, signOut: vi.fn() }),
}));

beforeEach(() => {
  cleanup();
  globalThis.fetch = vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderShell(pathname) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <AppShell>
        <div>route content</div>
      </AppShell>
    </MemoryRouter>
  );
}

function shellElement(container) {
  return container.querySelector('div.bg-theme-primary.text-theme-primary');
}

describe('AppShell — assessment workspace height chain', () => {
  it('locks the live assessment workspace to the viewport', () => {
    // A definite (non-percentage) height is what makes the `h-full` editor
    // containers inside the workspace resolve. Without it they fall back to
    // `auto`, which collapsed the WASM editor to a few pixels and let the
    // coding editor blow the page past the viewport.
    const { container } = renderShell('/assessment/attempt-1');
    const shell = shellElement(container);

    expect(shell).not.toBeNull();
    expect(shell.className).toMatch(/(^|\s)h-screen(\s|$)/);
    expect(shell.className).toMatch(/overflow-hidden/);
    expect(shell.className).not.toMatch(/min-h-screen/);
    expect(screen.getByText('route content')).toBeInTheDocument();
  });

  it.each([
    ['/domains'],
    ['/instructions'],
    ['/assessment/attempt-1/results'],
    ['/assessment/attempt-1/submitted'],
    ['/admin'],
  ])('keeps the scrolling shell on %s', (pathname) => {
    const { container } = renderShell(pathname);
    const shell = shellElement(container);

    expect(shell.className).toMatch(/min-h-screen/);
    expect(shell.className).not.toMatch(/(^|\s)h-screen(\s|$)/);
  });
});
