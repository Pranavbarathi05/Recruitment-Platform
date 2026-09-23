import { describe, it, expect, vi, beforeEach } from 'vitest';

// DuckDB-WASM cannot run in jsdom; the engine is stubbed with a fake that
// records the SQL it receives and can be told to fail specific statements.
const executed = [];
let onCreateTable = null;

function makeConn() {
  return {
    query: vi.fn(async (sql) => {
      executed.push(sql);
      if (onCreateTable && /^\s*CREATE\s+TABLE/i.test(sql)) {
        return onCreateTable(sql, executed);
      }
      return { toArray: () => [], schema: { fields: [] } };
    }),
    prepare: vi.fn(async () => ({
      query: vi.fn(async () => ({})),
      close: vi.fn(async () => {}),
    })),
    close: vi.fn(async () => {}),
  };
}

let conn;

vi.mock('@duckdb/duckdb-wasm', () => ({
  ConsoleLogger: class {},
  LogLevel: { WARNING: 1 },
  selectBundle: vi.fn(async () => ({ mainModule: 'm', mainWorker: 'w' })),
  AsyncDuckDB: class {
    async instantiate() {}
    async connect() {
      conn = makeConn();
      return conn;
    }
  },
}));

// Public-dir asset URLs (Vite `?url` imports) — never fetched here.
vi.mock('/duckdb/duckdb-mvp.wasm?url', () => ({ default: '/duckdb/duckdb-mvp.wasm' }));
vi.mock('/duckdb/duckdb-browser-mvp.worker.js?url', () => ({ default: '/duckdb/duckdb-browser-mvp.worker.js' }));
vi.mock('/duckdb/duckdb-eh.wasm?url', () => ({ default: '/duckdb/duckdb-eh.wasm' }));
vi.mock('/duckdb/duckdb-browser-eh.worker.js?url', () => ({ default: '/duckdb/duckdb-browser-eh.worker.js' }));

const SQL_SCHEMA = 'CREATE TABLE employees (\n id INTEGER,\n name VARCHAR\n);';
const SQL_DATASET = [
  { table: 'employees', columns: ['id', 'name'], rows: [[1, 'Alice'], [2, 'Bob']] },
];

async function freshRunner() {
  vi.resetModules();
  const mod = await import('./sqlWasmRunner');
  return mod;
}

beforeEach(() => {
  executed.length = 0;
  onCreateTable = null;
  conn = null;
  globalThis.Worker = class {
    constructor() {}
  };
});

describe('SqlWasmRunner initialisation', () => {
  it('creates the schema and loads the array dataset', async () => {
    const { SqlWasmRunner } = await freshRunner();
    const runner = new SqlWasmRunner();
    await runner.initialize({ schema: SQL_SCHEMA, dataset: SQL_DATASET });

    expect(executed.some((s) => /CREATE TABLE employees/i.test(s))).toBe(true);
    // Clean slate first, then the create and the inserts.
    const dropIdx = executed.findIndex((s) => /DROP TABLE IF EXISTS "employees"/i.test(s));
    const createIdx = executed.findIndex((s) => /CREATE TABLE employees/i.test(s));
    expect(dropIdx).toBeGreaterThanOrEqual(0);
    expect(createIdx).toBeGreaterThan(dropIdx);
  });

  it('can be initialised twice: the shared DB already holds the table', async () => {
    // Regression: the schema ran unguarded against a SHARED in-memory database,
    // so a second initialisation (React StrictMode double-mounts every effect,
    // and a resumed attempt remounts the challenge) died with
    // 'Catalog Error: Table with name "employees" already exists!' and the
    // challenge rendered no editor at all.
    const { SqlWasmRunner } = await freshRunner();
    const first = new SqlWasmRunner();
    await first.initialize({ schema: SQL_SCHEMA, dataset: SQL_DATASET });

    onCreateTable = () => {
      throw new Error('Catalog Error: Table with name "employees" already exists!');
    };
    const second = new SqlWasmRunner();
    await expect(
      second.initialize({ schema: SQL_SCHEMA, dataset: SQL_DATASET })
    ).resolves.toBeUndefined();
  });

  it('serialises concurrent initialisations instead of interleaving them', async () => {
    const { SqlWasmRunner } = await freshRunner();
    let inFlight = 0;
    let maxInFlight = 0;
    onCreateTable = async () => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((r) => setTimeout(r, 1));
      inFlight -= 1;
      return { toArray: () => [] };
    };

    const a = new SqlWasmRunner();
    const b = new SqlWasmRunner();
    await Promise.all([
      a.initialize({ schema: SQL_SCHEMA, dataset: SQL_DATASET }),
      b.initialize({ schema: SQL_SCHEMA, dataset: SQL_DATASET }),
    ]);

    // One problem load never runs inside another: the drop/create/insert
    // sequence stays atomic, so rows cannot be duplicated.
    expect(maxInFlight).toBe(1);
  });

  it('still surfaces unrelated initialisation failures', async () => {
    const { SqlWasmRunner } = await freshRunner();
    onCreateTable = () => {
      throw new Error('Catalog Error: Parser error: syntax error');
    };
    const runner = new SqlWasmRunner();
    await expect(
      runner.initialize({ schema: SQL_SCHEMA, dataset: SQL_DATASET })
    ).rejects.toThrow(/syntax error/);
  });

  it('loads the dataset with parameterised inserts', async () => {
    const { SqlWasmRunner } = await freshRunner();
    const runner = new SqlWasmRunner();
    await runner.initialize({ schema: SQL_SCHEMA, dataset: SQL_DATASET });

    expect(conn.prepare).toHaveBeenCalledWith(
      'INSERT INTO "employees" ("id", "name") VALUES (?, ?)'
    );
  });
});
