import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import Login from './Login';
import Signup from './Signup';

// Mock the auth hook so both pages see an authenticated session (no network).
vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    loading: false,
    signIn: vi.fn().mockResolvedValue({}),
    signUp: vi.fn().mockResolvedValue({}),
  }),
}));

vi.mock('../config', () => ({ default: { apiUrl: 'http://test' } }));

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/instructions" element={<div>INSTRUCTIONS_PAGE</div>} />
        <Route path="/domains" element={<div>DOMAINS_PAGE</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Authenticated landing redirect', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('visiting /login while authenticated redirects to /instructions', async () => {
    renderAt('/login');
    expect(await screen.findByText('INSTRUCTIONS_PAGE')).toBeInTheDocument();
    expect(screen.queryByText('DOMAINS_PAGE')).not.toBeInTheDocument();
  });

  it('visiting /signup while authenticated redirects to /instructions', async () => {
    renderAt('/signup');
    expect(await screen.findByText('INSTRUCTIONS_PAGE')).toBeInTheDocument();
    expect(screen.queryByText('DOMAINS_PAGE')).not.toBeInTheDocument();
  });
});
