import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminCoding from './AdminCoding';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

const PROBLEM = {
  id: 'p1',
  title: 'Count Matches',
  slug: 'count-matches',
  description: 'Return the number of matches.',
  difficulty: 'easy',
  constraints: '',
  input_format: '',
  output_format: '',
  explanation: '',
  points: 10,
  time_limit_ms: 2000,
  memory_limit_mb: 256,
  supported_languages: ['python3'],
  is_active: true,
  starter_code: { python3: '' },
  function_name: 'solve',
  class_name: '',
  function_signature: '',
  public_test_count: 0,
  total_test_count: 0,
};

// The exact public bulk-upload format the admin UI documents.
const BULK_JSON = JSON.stringify([
  { arguments: [[1, 1, 1], 2], expected_output: 2, is_public: true, points: 1 },
  { arguments: [[1, -1, 0], 0], expected_output: 3, is_public: false, points: 2 },
]);

let testCases;
let bulkPosts;
let createPosts;

/**
 * Fake backend that echoes rows the way the real endpoints do:
 * `arguments` comes back as a JSON array, `input` as the mirrored JSON text.
 */
function mockFetch() {
  return vi.fn(async (url, options = {}) => {
    const u = String(url);
    const method = (options.method || 'GET').toUpperCase();

    if (u.includes('/tests/bulk') && method === 'POST') {
      const body = JSON.parse(options.body);
      bulkPosts.push(body);
      const created = body.test_cases.map((tc, i) => ({
        id: `tc-${i}`,
        arguments: tc.arguments,
        expected_output: tc.expected_output,
        is_public: tc.is_public,
        points: tc.points,
        ordering: tc.ordering ?? i,
        input: JSON.stringify(tc.arguments),
      }));
      testCases = [...testCases, ...created];
      return {
        ok: true,
        status: 201,
        json: async () => ({ status: 'created', count: created.length, test_cases: created }),
      };
    }

    if (u.includes('/tests') && method === 'POST') {
      const body = JSON.parse(options.body);
      createPosts.push(body);
      const created = { id: 'new-tc', ordering: body.ordering, input: JSON.stringify(body.arguments), ...body };
      testCases = [...testCases, created];
      return { ok: true, status: 201, json: async () => created };
    }

    if (u.includes('/tests')) {
      return { ok: true, status: 200, json: async () => testCases };
    }

    if (u.includes('/admin/coding/problems')) {
      return { ok: true, status: 200, json: async () => [PROBLEM] };
    }

    if (u.includes('/admin/domains')) {
      return { ok: true, status: 200, json: async () => [] };
    }

    return { ok: true, status: 200, json: async () => ({}) };
  });
}

async function openBulkUpload() {
  render(
    <MemoryRouter>
      <AdminCoding />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByText('Count Matches'));
  fireEvent.click(await screen.findByRole('button', { name: /Bulk Upload/ }));
  return screen.getByPlaceholderText(/^\[\{"arguments"/);
}

describe('AdminCoding — bulk test case upload', () => {
  beforeEach(() => {
    testCases = [];
    bulkPosts = [];
    createPosts = [];
    globalThis.fetch = mockFetch();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('posts the documented public payload unchanged', async () => {
    const textarea = await openBulkUpload();
    fireEvent.change(textarea, { target: { value: BULK_JSON } });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));

    await waitFor(() => expect(bulkPosts).toHaveLength(1));

    // The admin keeps authoring `arguments`/`expected_output`; no database
    // column names (`input`) leak into the request.
    expect(bulkPosts[0]).toEqual({
      test_cases: [
        { arguments: [[1, 1, 1], 2], expected_output: 2, is_public: true, points: 1 },
        { arguments: [[1, -1, 0], 0], expected_output: 3, is_public: false, points: 2 },
      ],
    });
    expect(bulkPosts[0].test_cases[0]).not.toHaveProperty('input');
  });

  it('shows the uploaded cases in the admin list with their visibility and points', async () => {
    const textarea = await openBulkUpload();
    fireEvent.change(textarea, { target: { value: BULK_JSON } });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));

    await waitFor(() => expect(screen.getByText(/Uploaded 2 test cases/)).toBeInTheDocument());

    expect(await screen.findByText(/Test 1 \(1 pts\)/)).toBeInTheDocument();
    expect(screen.getByText(/Test 2 \(2 pts\)/)).toBeInTheDocument();
    expect(screen.getByText(/HIDDEN — Test 2/)).toBeInTheDocument();
    // The JSON arguments array of the uploaded case is rendered as-is
    // (whitespace is normalized by testing-library).
    expect(screen.getByText(/1,\s*-1,\s*0/)).toBeInTheDocument();
  });

  it('rejects a non-array test case before hitting the API', async () => {
    const textarea = await openBulkUpload();
    fireEvent.change(textarea, {
      target: { value: JSON.stringify([{ arguments: 5, expected_output: 2 }]) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));

    expect(await screen.findByText(/arguments must be a JSON array/)).toBeInTheDocument();
    expect(bulkPosts).toHaveLength(0);
  });
});

describe('AdminCoding — individual test case creation', () => {
  beforeEach(() => {
    testCases = [];
    bulkPosts = [];
    createPosts = [];
    globalThis.fetch = mockFetch();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('sends arguments/expected_output and relies on the backend input mapping', async () => {
    render(
      <MemoryRouter>
        <AdminCoding />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByText('Count Matches'));
    fireEvent.click(await screen.findByRole('button', { name: /Add Test Case/ }));

    fireEvent.change(screen.getByPlaceholderText('[[2,7,11,15], 9]'), {
      target: { value: '[[2,7,11,15], 9]' },
    });
    fireEvent.change(screen.getByPlaceholderText('[0,1]'), {
      target: { value: '[0,1]' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => expect(createPosts).toHaveLength(1));

    expect(createPosts[0]).toEqual({
      arguments: [[2, 7, 11, 15], 9],
      expected_output: [0, 1],
      is_public: false,
      points: 1,
      ordering: 0,
    });
    expect(createPosts[0]).not.toHaveProperty('input');
  });
});
