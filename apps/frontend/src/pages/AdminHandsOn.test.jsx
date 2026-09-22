import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminHandsOn from './AdminHandsOn';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

const DEVOPS = { id: 'dom-devops', name: 'DevOps', is_active: true };
const ML = { id: 'dom-ml', name: 'Machine Learning', is_active: true };

// The dataset is stored as a JSONB ARRAY of table specs — exactly what the
// browser-side DuckDB/Pyodide runners consume. The backend schema used to
// declare it as a dict, so saving an existing challenge answered 422.
const WASM_DATASET = [
  { table: 'employees', columns: ['id', 'department'], rows: [[1, 'Engineering']] },
];

const WASM_CHALLENGE = {
  id: 'h1',
  title: 'Employee Analytics — SQL',
  description: 'Average salary per department.',
  domain_ids: [],
  challenge_type: 'sql_wasm',
  difficulty: 'easy',
  points: 100,
  challenge_url: '',
  expected_flag: '',
  is_active: true,
  schema_sql: 'CREATE TABLE employees (id INTEGER);',
  dataset_json: WASM_DATASET,
  starter_code: 'SELECT * FROM employees;',
  validation_spec: { expected_columns: ['id'] },
  expected_answer: 'reference',
  domain_names: [],
};

let challenges;

function mockFetch(putResponse) {
  return vi.fn(async (url, options = {}) => {
    const u = String(url);
    const method = (options.method || 'GET').toUpperCase();

    if (u.includes('/admin/hands-on-questions') && method === 'PUT') {
      return putResponse();
    }
    if (u.includes('/admin/hands-on-questions')) {
      return { ok: true, status: 200, json: async () => challenges };
    }
    if (u.includes('/admin/domains')) {
      return { ok: true, status: 200, json: async () => [DEVOPS, ML] };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

function putBody(fetchMock) {
  const call = fetchMock.mock.calls.find(([, o]) => (o?.method || '').toUpperCase() === 'PUT');
  return JSON.parse(call[1].body);
}

/** Open the admin page, select the WASM challenge and enter its edit form. */
async function openEditForm() {
  render(
    <MemoryRouter>
      <AdminHandsOn />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByText('Employee Analytics — SQL'));
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
}

describe('AdminHandsOn — challenge domain configuration', () => {
  beforeEach(() => {
    challenges = [{ ...WASM_CHALLENGE }];
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders the challenge list with its domains and the domain checkboxes', async () => {
    globalThis.fetch = mockFetch(() => ({ ok: true, status: 200, json: async () => ({}) }));
    await openEditForm();

    expect(screen.getByLabelText('DevOps')).toBeInTheDocument();
    expect(screen.getByLabelText('Machine Learning')).toBeInTheDocument();
  });

  it('saves a WASM challenge assigned to a domain and reports success', async () => {
    const fetchMock = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ ...WASM_CHALLENGE, domain_ids: [DEVOPS.id] }),
    }));
    globalThis.fetch = fetchMock;
    await openEditForm();

    fireEvent.click(screen.getByLabelText('DevOps'));
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    await waitFor(() =>
      expect(screen.getByText('Challenge updated successfully.')).toBeInTheDocument(),
    );

    const body = putBody(fetchMock);
    expect(body.domain_ids).toEqual([DEVOPS.id]);
    expect(body.dataset_json).toEqual(WASM_DATASET);
    expect(screen.queryByText(/\[object Object\]/)).toBeNull();
  });

  it('saves multiple domains when several are selected', async () => {
    const fetchMock = mockFetch(() => ({ ok: true, status: 200, json: async () => ({}) }));
    globalThis.fetch = fetchMock;
    await openEditForm();

    fireEvent.click(screen.getByLabelText('DevOps'));
    fireEvent.click(screen.getByLabelText('Machine Learning'));
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    await waitFor(() => expect(putBody(fetchMock)).toBeTruthy());
    expect(putBody(fetchMock).domain_ids).toEqual([DEVOPS.id, ML.id]);
  });

  it('unassigning a domain sends an empty domain list', async () => {
    challenges = [{ ...WASM_CHALLENGE, domain_ids: [DEVOPS.id] }];
    const fetchMock = mockFetch(() => ({ ok: true, status: 200, json: async () => ({}) }));
    globalThis.fetch = fetchMock;
    await openEditForm();

    expect(screen.getByLabelText('DevOps')).toBeChecked();
    fireEvent.click(screen.getByLabelText('DevOps'));
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    await waitFor(() => expect(putBody(fetchMock)).toBeTruthy());
    expect(putBody(fetchMock).domain_ids).toEqual([]);
  });

  it('shows the backend validation error instead of [object Object]', async () => {
    // FastAPI 422: detail is an array of {loc, msg} objects. Interpolating it
    // printed "Error: [object Object]" and hid the real cause.
    globalThis.fetch = mockFetch(() => ({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [
          {
            type: 'dict_type',
            loc: ['body', 'dataset_json'],
            msg: 'Input should be a valid dictionary',
          },
        ],
      }),
    }));
    await openEditForm();

    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    const banner = await screen.findByText(/dataset_json: Input should be a valid dictionary/);
    expect(banner).toBeInTheDocument();
    expect(banner.textContent.startsWith('Error:')).toBe(true);
    expect(screen.queryByText(/\[object Object\]/)).toBeNull();
  });

  it('shows a plain-text backend error message', async () => {
    globalThis.fetch = mockFetch(() => ({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'One or more domain IDs not found' }),
    }));
    await openEditForm();

    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    expect(
      await screen.findByText('Error: One or more domain IDs not found'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\[object Object\]/)).toBeNull();
  });

  it('falls back to a readable message when the error body is not JSON', async () => {
    globalThis.fetch = mockFetch(() => ({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('Unexpected token < in JSON');
      },
      text: async () => 'Bad Gateway',
    }));
    await openEditForm();

    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    expect(await screen.findByText('Error: Bad Gateway')).toBeInTheDocument();
    expect(screen.queryByText(/\[object Object\]/)).toBeNull();
  });

  it('surfaces deletion errors (e.g. an in-use 409) verbatim', async () => {
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const u = String(url);
      const method = (options.method || 'GET').toUpperCase();
      if (u.includes('/admin/hands-on-questions') && method === 'DELETE') {
        return {
          ok: false,
          status: 409,
          json: async () => ({
            detail:
              'Cannot delete: challenge is referenced by existing attempts. Use deactivation instead.',
          }),
        };
      }
      if (u.includes('/admin/hands-on-questions')) {
        return { ok: true, status: 200, json: async () => challenges };
      }
      if (u.includes('/admin/domains')) {
        return { ok: true, status: 200, json: async () => [DEVOPS, ML] };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(
      <MemoryRouter>
        <AdminHandsOn />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByText('Employee Analytics — SQL'));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(
      await screen.findByText(/Error: Cannot delete: challenge is referenced/),
    ).toBeInTheDocument();
  });
});
