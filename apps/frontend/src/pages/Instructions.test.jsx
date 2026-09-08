import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Instructions from './Instructions';

// Mock useNavigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => mockNavigate };
});

describe('Instructions Page', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('renders the page heading', () => {
    render(<MemoryRouter><Instructions /></MemoryRouter>);
    expect(screen.getByText('Assessment Instructions')).toBeInTheDocument();
  });

  it('renders the Coding section', () => {
    render(<MemoryRouter><Instructions /></MemoryRouter>);
    expect(screen.getByText(/Coding/)).toBeInTheDocument();
    expect(screen.getByText(/integrated code editor/)).toBeInTheDocument();
  });

  it('renders the MCQs section', () => {
    render(<MemoryRouter><Instructions /></MemoryRouter>);
    expect(screen.getByText(/MCQs/)).toBeInTheDocument();
    expect(screen.getByText(/Multiple-choice questions/)).toBeInTheDocument();
  });

  it('renders the Next button', () => {
    render(<MemoryRouter><Instructions /></MemoryRouter>);
    expect(screen.getByText(/Next →/)).toBeInTheDocument();
  });

  it('navigates to /domains when Next is clicked', () => {
    render(<MemoryRouter><Instructions /></MemoryRouter>);
    fireEvent.click(screen.getByText(/Next →/));
    expect(mockNavigate).toHaveBeenCalledWith('/domains');
  });
});
