/**
 * SqlWasmRunner — Reusable browser-local SQL execution engine using DuckDB-WASM.
 *
 * Interface:
 *   initialize(problem)  — create DB, load schema + dataset
 *   execute(sql)         — run candidate SQL, return {columns, rows, duration, error}
 *   reset()              — drop all tables, reinitialize
 *   dispose()            — tear down the database entirely
 *
 * All execution is 100% client-side. Candidate SQL is NEVER sent to the backend.
 * DuckDB assets are served locally from /duckdb/ (no CDN).
 */
import * as duckdb from '@duckdb/duckdb-wasm';

// Assets served locally (copied by scripts/copy-duckdb.mjs)
import duckdbMvpUrl from '/duckdb/duckdb-mvp.wasm?url';
import mvpWorkerUrl from '/duckdb/duckdb-browser-mvp.worker.js?url';
import duckdbEhUrl from '/duckdb/duckdb-eh.wasm?url';
import ehWorkerUrl from '/duckdb/duckdb-browser-eh.worker.js?url';

const BUNDLES = {
  mvp: { mainModule: duckdbMvpUrl, mainWorker: mvpWorkerUrl },
  eh: { mainModule: duckdbEhUrl, mainWorker: ehWorkerUrl },
};

// Shared singleton so multiple challenges share one DuckDB instance
let _dbInstance = null;
let _initPromise = null;

/**
 * Get or create the shared AsyncDuckDB instance.
 */
async function getDb() {
  if (_dbInstance) return _dbInstance;
  if (_initPromise) return _initPromise;

  _initPromise = (async () => {
    const bundle = await duckdb.selectBundle(BUNDLES);
    const worker = new Worker(bundle.mainWorker);
    const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
    const db = new duckdb.AsyncDuckDB(logger, worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    _dbInstance = db;
    return db;
  })();

  try {
    return await _initPromise;
  } catch (err) {
    _initPromise = null;
    throw err;
  }
}

export class SqlWasmRunner {
  constructor() {
    this._conn = null;
    this._db = null;
    this._problem = null;
    this._initialized = false;
  }

  /**
   * Initialize the runner with a problem definition.
   * Creates an in-memory database, creates schema, and loads the dataset.
   *
   * @param {Object} problem - Challenge definition with:
   *   problem.schema - SQL CREATE statements or table definitions
   *   problem.dataset - Array of { table, columns, rows } or INSERT statements
   */
  async initialize(problem) {
    this._problem = problem;
    this._db = await getDb();
    this._conn = await this._db.connect();

    // Configure for local-only execution
    await this._conn.query(`
      SET enable_progress_bar = false;
    `);

    // Create schema
    await this._loadSchema(problem.schema);

    // Load dataset
    await this._loadDataset(problem.dataset);

    this._initialized = true;
  }

  /**
   * Execute candidate SQL and return structured results.
   *
   * @param {string} sql - Candidate's SQL query
   * @returns {{ columns: string[], rows: any[][], duration: number, error: string|null }}
   */
  async execute(sql) {
    if (!this._initialized || !this._conn) {
      throw new Error('SqlWasmRunner not initialized. Call initialize() first.');
    }

    const startTime = performance.now();
    try {
      const result = await this._conn.query(sql);
      const duration = performance.now() - startTime;

      // Extract column names
      const columns = result.schema.fields.map((f) => f.name);

      // Extract rows as arrays of JS values
      const arrowRows = result.toArray();
      const rows = arrowRows.map((row) => {
        return columns.map((col) => {
          const val = row[col];
          // Convert BigInt to Number for JSON serialization
          if (typeof val === 'bigint') return Number(val);
          return val;
        });
      });

      return { columns, rows, duration: Math.round(duration * 100) / 100, error: null };
    } catch (err) {
      const duration = performance.now() - startTime;
      return {
        columns: [],
        rows: [],
        duration: Math.round(duration * 100) / 100,
        error: err.message || String(err),
      };
    }
  }

  /**
   * Reset the database: drop all tables and reload the dataset.
   */
  async reset() {
    if (!this._conn || !this._problem) return;

    // Drop all user tables
    const tables = await this._conn.query(`
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = 'main'
    `);
    const tableRows = tables.toArray();
    for (const row of tableRows) {
      await this._conn.query(`DROP TABLE IF EXISTS "${row.table_name}"`);
    }

    // Reload
    await this._loadSchema(this._problem.schema);
    await this._loadDataset(this._problem.dataset);
  }

  /**
   * Dispose of the connection. The shared DB instance persists for reuse.
   */
  async dispose() {
    if (this._conn) {
      try {
        await this._conn.close();
      } catch {
        // ignore
      }
      this._conn = null;
    }
    this._initialized = false;
    this._problem = null;
  }

  // ---- Private helpers ----

  async _loadSchema(schema) {
    if (!schema) return;

    if (typeof schema === 'string') {
      // Single SQL CREATE statement or multiple statements
      const stmts = schema.split(';').map((s) => s.trim()).filter(Boolean);
      for (const stmt of stmts) {
        await this._conn.query(stmt);
      }
    } else if (Array.isArray(schema)) {
      for (const stmt of schema) {
        if (typeof stmt === 'string') {
          await this._conn.query(stmt);
        } else if (stmt.sql) {
          await this._conn.query(stmt.sql);
        }
      }
    }
  }

  async _loadDataset(dataset) {
    if (!dataset) return;

    if (Array.isArray(dataset)) {
      // Array of { table, columns, rows } objects
      for (const entry of dataset) {
        if (entry.sql) {
          // Direct SQL INSERT statements
          const stmts = entry.sql.split(';').map((s) => s.trim()).filter(Boolean);
          for (const stmt of stmts) {
            await this._conn.query(stmt);
          }
          continue;
        }

        const { table, columns, rows } = entry;
        if (!table || !columns || !rows || !rows.length) continue;

        // Build INSERT statement with parameterized values
        const placeholders = columns.map(() => '?').join(', ');
        const insertSql = `INSERT INTO "${table}" (${columns.map((c) => `"${c}"`).join(', ')}) VALUES (${placeholders})`;

        // Use DuckDB's prepared statement for efficiency
        const stmt = await this._conn.prepare(insertSql);
        for (const row of rows) {
          // Convert values for DuckDB compatibility
          const params = row.map((v) => {
            if (v === null || v === undefined) return null;
            if (typeof v === 'number' && !Number.isFinite(v)) return null;
            return v;
          });
          await stmt.bind(params);
          await stmt.execute();
        }
        await stmt.close();
      }
    } else if (typeof dataset === 'string') {
      // Raw SQL INSERT statements
      const stmts = dataset.split(';').map((s) => s.trim()).filter(Boolean);
      for (const stmt of stmts) {
        await this._conn.query(stmt);
      }
    }
  }
}

/**
 * Lazily initialize DuckDB. Called when an sql_wasm challenge is first opened.
 * Returns a promise that resolves when DuckDB is ready.
 */
export async function initSqlWasm() {
  return getDb();
}

/**
 * Check if DuckDB-WASM is available in this browser.
 */
export function isSqlWasmSupported() {
  return typeof WebAssembly !== 'undefined';
}
