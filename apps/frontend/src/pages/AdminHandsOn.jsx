import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * Admin Hands-On Challenges Page
 *
 * Admin management for hands-on challenges:
 * - SQL Injection micro-CTF (existing)
 * - SQL WASM (DuckDB-WASM, browser-local execution)
 * - Pandas WASM (Pyodide, browser-local execution)
 *
 * Features:
 * - Create/edit/delete challenges
 * - Fixed challenge type registry
 * - Difficulty + points configuration
 * - Expected flag (CTF) or validation spec (WASM)
 * - Multi-domain assignment
 */

const CHALLENGE_TYPES = [
  { value: 'sql_injection_employee_portal', label: 'SQL Injection — Employee Portal' },
  { value: 'sql_wasm', label: 'SQL WASM (DuckDB, browser-local)' },
  { value: 'pandas_wasm', label: 'Pandas WASM (Pyodide, browser-local)' },
];
const DIFFICULTIES = ['easy', 'medium', 'hard'];

const EMPTY_FORM = {
  title: '',
  description: '',
  domain_ids: [],
  challenge_type: 'sql_wasm',
  difficulty: 'medium',
  points: 100,
  challenge_url: '',
  expected_flag: '',
  is_active: true,
  // WASM fields
  schema_sql: '',
  dataset_json_text: '',
  starter_code: '',
  validation_spec_text: '',
  expected_answer: '',
};

const AdminHandsOn = () => {
  const { getAuthHeaders } = useAuth();
  const navigate = useNavigate();

  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  const [questions, setQuestions] = useState([]);
  const [selectedQuestion, setSelectedQuestion] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editingQuestion, setEditingQuestion] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [domains, setDomains] = useState([]);
  const [message, setMessage] = useState('');

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const isWasmType = form.challenge_type === 'sql_wasm' || form.challenge_type === 'pandas_wasm';

  // Admin check
  useEffect(() => {
    let cancelled = false;
    const checkAdmin = async () => {
      try {
        const resp = await fetch(`${apiUrl}/admin/domains`, { credentials: 'include' });
        if (cancelled) return;
        if (resp.ok) {
          setIsAdmin(true);
          setLoading(false);
        } else if (resp.status === 403) {
          navigate('/domains');
        } else if (resp.status === 401) {
          navigate('/login');
        } else {
          setMessage('Error: Could not verify admin status.');
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setMessage('Error: Could not connect to the server.');
          setLoading(false);
        }
      }
    };
    checkAdmin();
    return () => { cancelled = true; };
  }, [apiUrl, navigate]);

  const fetchDomains = useCallback(async () => {
    try {
      const resp = await fetch(`${apiUrl}/admin/domains`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setDomains(data);
      }
    } catch { /* silent */ }
  }, [apiUrl]);

  const fetchQuestions = useCallback(async () => {
    try {
      const resp = await fetch(`${apiUrl}/admin/hands-on-questions`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setQuestions(data);
      }
    } catch { /* silent */ }
  }, [apiUrl]);

  useEffect(() => {
    if (isAdmin) {
      fetchDomains();
      fetchQuestions();
    }
  }, [isAdmin, fetchDomains, fetchQuestions]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        title: form.title,
        description: form.description,
        domain_ids: form.domain_ids,
        challenge_type: form.challenge_type,
        difficulty: form.difficulty,
        points: parseInt(form.points, 10) || 100,
        is_active: form.is_active,
      };

      if (isWasmType) {
        // WASM challenges: dataset and validation_spec are required
        let datasetJson = null;
        let validationSpec = null;
        try {
          datasetJson = form.dataset_json_text.trim() ? JSON.parse(form.dataset_json_text) : null;
        } catch {
          setMessage('Error: Invalid JSON in Dataset JSON');
          return;
        }
        try {
          validationSpec = form.validation_spec_text.trim() ? JSON.parse(form.validation_spec_text) : null;
        } catch {
          setMessage('Error: Invalid JSON in Validation Spec');
          return;
        }

        payload.schema_sql = form.schema_sql || null;
        payload.dataset_json = datasetJson;
        payload.starter_code = form.starter_code || null;
        payload.validation_spec = validationSpec;
        payload.expected_answer = form.expected_answer || null;
        // WASM types don't use challenge_url or expected_flag
        payload.challenge_url = '';
        payload.expected_flag = '';
      } else {
        // CTF challenge: challenge_url and expected_flag are required
        payload.challenge_url = form.challenge_url;
        payload.expected_flag = form.expected_flag.trim();
      }

      const isEditing = !!editingQuestion;
      const url = isEditing
        ? `${apiUrl}/admin/hands-on-questions/${editingQuestion.id}`
        : `${apiUrl}/admin/hands-on-questions`;

      const resp = await fetch(url, {
        method: isEditing ? 'PUT' : 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      });

      if (resp.ok) {
        setMessage(isEditing ? 'Challenge updated successfully.' : 'Challenge created successfully.');
        setShowForm(false);
        setEditingQuestion(null);
        setForm(EMPTY_FORM);
        fetchQuestions();
      } else {
        const err = await resp.json();
        setMessage(`Error: ${err.detail || 'Failed to save challenge'}`);
      }
    } catch (err) {
      setMessage(`Error: ${err.message}`);
    }
  };

  const handleDelete = async (questionId) => {
    if (!window.confirm('Are you sure you want to delete this challenge?')) return;
    try {
      const resp = await fetch(`${apiUrl}/admin/hands-on-questions/${questionId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
      });
      if (resp.ok) {
        setMessage('Challenge deleted successfully.');
        setSelectedQuestion(null);
        fetchQuestions();
      } else {
        const err = await resp.json();
        setMessage(`Error: ${err.detail || 'Failed to delete'}`);
      }
    } catch (err) {
      setMessage(`Error: ${err.message}`);
    }
  };

  const handleEdit = (q) => {
    setEditingQuestion(q);
    setForm({
      title: q.title || '',
      description: q.description || '',
      domain_ids: q.domain_ids || [],
      challenge_type: q.challenge_type || 'sql_injection_employee_portal',
      difficulty: q.difficulty || 'medium',
      points: q.points ?? 100,
      challenge_url: q.challenge_url || '',
      expected_flag: q.expected_flag || '',
      is_active: q.is_active,
      schema_sql: q.schema_sql || '',
      dataset_json_text: q.dataset_json ? JSON.stringify(q.dataset_json, null, 2) : '',
      starter_code: q.starter_code || '',
      validation_spec_text: q.validation_spec ? JSON.stringify(q.validation_spec, null, 2) : '',
      expected_answer: q.expected_answer || '',
    });
    setShowForm(true);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-blue-500" />
      </div>
    );
  }

  if (!isAdmin) return null;

  return (
    <div className="min-h-screen bg-theme-primary py-12 px-4">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/admin')}
              className="text-theme-muted hover:text-theme-primary transition-colors"
            >
              ← Back to Admin
            </button>
            <h1 className="text-3xl font-bold text-theme-primary">Hands-On Challenges</h1>
          </div>
          <button
            onClick={() => {
              setEditingQuestion(null);
              setForm(EMPTY_FORM);
              setShowForm(true);
            }}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold"
          >
            + Add Challenge
          </button>
        </div>

        {message && (
          <div className={`mb-4 p-3 rounded-lg text-sm ${message.startsWith('Error') ? 'bg-red-900/30 border border-red-500 text-red-300' : 'bg-green-900/30 border border-green-500 text-green-300'}`}>
            {message}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Challenges List */}
          <div className="lg:col-span-1">
            <h2 className="text-xl font-bold text-theme-primary mb-4">Challenges ({questions.length})</h2>
            <div className="space-y-2">
              {questions.map((q) => (
                <div
                  key={q.id}
                  onClick={() => setSelectedQuestion(q)}
                  className={`bg-theme-secondary rounded-lg p-3 cursor-pointer transition-all ${selectedQuestion?.id === q.id ? 'ring-2 ring-blue-500' : 'hover:bg-theme-tertiary'}`}
                >
                  <div className="flex justify-between items-start">
                    <p className="text-sm text-theme-primary font-medium flex-1">{q.title}</p>
                    <span className={`text-xs px-2 py-0.5 rounded ml-2 flex-shrink-0 ${q.is_active ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
                      {q.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    <span className="text-xs px-2 py-0.5 bg-purple-900/50 text-purple-300 rounded capitalize">{q.difficulty}</span>
                    <span className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">{q.points} pts</span>
                    <span className="text-xs px-2 py-0.5 bg-orange-900/50 text-orange-300 rounded">{q.challenge_type}</span>
                    {(q.domain_names || []).map((name, i) => (
                      <span key={i} className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">{name}</span>
                    ))}
                  </div>
                </div>
              ))}
              {questions.length === 0 && (
                <p className="text-theme-muted text-center py-8">No hands-on challenges yet.</p>
              )}
            </div>
          </div>

          {/* Detail / Form Panel */}
          <div className="lg:col-span-2">
            {showForm ? (
              <form onSubmit={handleSubmit} className="bg-theme-secondary rounded-lg p-6 space-y-4">
                <h2 className="text-xl font-bold text-theme-primary mb-2">
                  {editingQuestion ? 'Edit Challenge' : 'Create Challenge'}
                </h2>

                <div>
                  <label className="block text-sm font-medium text-theme-primary mb-1">Title *</label>
                  <input
                    value={form.title}
                    onChange={(e) => setForm({ ...form, title: e.target.value })}
                    required
                    className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    placeholder="e.g. Employee Analytics — SQL"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-theme-primary mb-1">Description (shown to candidates) *</label>
                  <textarea
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    required
                    rows={4}
                    className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    placeholder="Describe the objective..."
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-theme-primary mb-1">Challenge Type *</label>
                    <select
                      value={form.challenge_type}
                      onChange={(e) => setForm({ ...form, challenge_type: e.target.value })}
                      className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    >
                      {CHALLENGE_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-theme-primary mb-1">Difficulty</label>
                    <select
                      value={form.difficulty}
                      onChange={(e) => setForm({ ...form, difficulty: e.target.value })}
                      className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    >
                      {DIFFICULTIES.map((d) => (
                        <option key={d} value={d} className="capitalize">{d}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-theme-primary mb-1">Points</label>
                  <input
                    type="number"
                    min="0"
                    max="1000"
                    value={form.points}
                    onChange={(e) => setForm({ ...form, points: e.target.value })}
                    className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                  />
                </div>

                {/* CTF-only fields */}
                {!isWasmType && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-theme-primary mb-1">Challenge URL *</label>
                      <input
                        value={form.challenge_url}
                        onChange={(e) => setForm({ ...form, challenge_url: e.target.value })}
                        required
                        className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                        placeholder="/challenge/ (served via the Gateway)"
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-theme-primary mb-1">Expected Flag * (admin-only secret)</label>
                      <input
                        value={form.expected_flag}
                        onChange={(e) => setForm({ ...form, expected_flag: e.target.value })}
                        required
                        className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm font-mono"
                        placeholder="FLAG{...}"
                      />
                      <p className="text-xs text-theme-muted mt-1">
                        Stored server-side only. Never sent to candidates.
                      </p>
                    </div>
                  </>
                )}

                {/* WASM-only fields */}
                {isWasmType && (
                  <>
                    <div className="bg-blue-900/20 border border-blue-500/30 rounded-lg p-3 text-xs text-blue-300">
                      Browser-local execution: {form.challenge_type === 'sql_wasm' ? 'DuckDB-WASM' : 'Pyodide + Pandas'}. No server-side execution.
                    </div>

                    {form.challenge_type === 'sql_wasm' && (
                      <div>
                        <label className="block text-sm font-medium text-theme-primary mb-1">Schema SQL (CREATE TABLE statements)</label>
                        <textarea
                          value={form.schema_sql}
                          onChange={(e) => setForm({ ...form, schema_sql: e.target.value })}
                          rows={5}
                          className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm font-mono"
                          placeholder={'CREATE TABLE employees (\n  id INTEGER,\n  name VARCHAR,\n  department VARCHAR,\n  salary DOUBLE\n);'}
                        />
                      </div>
                    )}

                    <div>
                      <label className="block text-sm font-medium text-theme-primary mb-1">Dataset JSON * ({form.challenge_type === 'sql_wasm' ? 'table, columns, rows' : 'name, columns, data'})</label>
                      <textarea
                        value={form.dataset_json_text}
                        onChange={(e) => setForm({ ...form, dataset_json_text: e.target.value })}
                        rows={8}
                        required
                        className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm font-mono"
                        placeholder={form.challenge_type === 'sql_wasm'
                          ? '[{"table": "employees", "columns": ["id", "name", "department", "salary"], "rows": [[1, "Alice", "Engineering", 80000]]}]'
                          : '[{"name": "df", "columns": ["name", "department", "salary"], "data": [["Alice", "Engineering", 80000]]}]'
                        }
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-theme-primary mb-1">Starter Code</label>
                      <textarea
                        value={form.starter_code}
                        onChange={(e) => setForm({ ...form, starter_code: e.target.value })}
                        rows={5}
                        className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm font-mono"
                        placeholder={form.challenge_type === 'sql_wasm'
                          ? 'SELECT department, AVG(salary) as avg_salary\nFROM employees\nGROUP BY department;'
                          : 'result = df.groupby("department")["salary"].mean().reset_index()'
                        }
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-theme-primary mb-1">Validation Spec JSON *</label>
                      <textarea
                        value={form.validation_spec_text}
                        onChange={(e) => setForm({ ...form, validation_spec_text: e.target.value })}
                        rows={8}
                        required
                        className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm font-mono"
                        placeholder={form.challenge_type === 'sql_wasm'
                          ? '{"expected_columns": ["department", "avg_salary"], "expected_rows": [["Engineering", 75000.0]], "order_sensitive": false, "numeric_tolerance": 1.0}'
                          : '{"expected_columns": ["department", "salary"], "expected_values": [["Engineering", 75000.0]], "order_sensitive": false, "numeric_tolerance": 1.0}'
                        }
                      />
                      <p className="text-xs text-theme-muted mt-1">
                        Determines client-side scoring. Fields: expected_columns, expected_rows/values, expected_shape, order_sensitive, numeric_tolerance, expect_error.
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-theme-primary mb-1">Expected Answer (admin-only, never sent to candidate)</label>
                      <textarea
                        value={form.expected_answer}
                        onChange={(e) => setForm({ ...form, expected_answer: e.target.value })}
                        rows={3}
                        className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm font-mono"
                        placeholder="Reference answer for admin review"
                      />
                    </div>
                  </>
                )}

                {/* Domain Selection */}
                <div>
                  <label className="block text-sm font-medium text-theme-primary mb-1">Domains</label>
                  <div className="space-y-1">
                    {domains.map((d) => (
                      <label key={d.id} className="flex items-center gap-2 text-sm text-theme-primary cursor-pointer">
                        <input
                          type="checkbox"
                          checked={form.domain_ids.includes(d.id)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setForm({ ...form, domain_ids: [...form.domain_ids, d.id] });
                            } else {
                              setForm({ ...form, domain_ids: form.domain_ids.filter((id) => id !== d.id) });
                            }
                          }}
                          className="rounded"
                        />
                        {d.name}
                      </label>
                    ))}
                  </div>
                </div>

                {/* Active toggle */}
                <label className="flex items-center gap-2 text-sm text-theme-primary cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                    className="rounded"
                  />
                  Active
                </label>

                <div className="flex gap-2 pt-2">
                  <button type="submit" className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm font-semibold">
                    {editingQuestion ? 'Update' : 'Create'}
                  </button>
                  <button type="button" onClick={() => { setShowForm(false); setEditingQuestion(null); }} className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded text-sm">
                    Cancel
                  </button>
                </div>
              </form>
            ) : selectedQuestion ? (
              <div className="bg-theme-secondary rounded-lg p-6">
                <div className="flex justify-between items-start mb-4">
                  <h2 className="text-xl font-bold text-theme-primary">Challenge Detail</h2>
                  <div className="flex gap-2">
                    <button onClick={() => handleEdit(selectedQuestion)} className="text-xs px-3 py-1 bg-blue-600 text-white rounded">Edit</button>
                    <button onClick={() => handleDelete(selectedQuestion.id)} className="text-xs px-3 py-1 bg-red-600 text-white rounded">Delete</button>
                  </div>
                </div>
                <p className="text-theme-primary font-semibold text-lg mb-2">{selectedQuestion.title}</p>
                <p className="text-theme-primary whitespace-pre-wrap mb-4">{selectedQuestion.description}</p>
                <div className="grid grid-cols-2 gap-2 text-sm mb-2">
                  <span className="text-theme-muted">Type:</span>
                  <span className="text-theme-primary">{selectedQuestion.challenge_type}</span>
                  <span className="text-theme-muted">Difficulty:</span>
                  <span className="text-theme-primary capitalize">{selectedQuestion.difficulty}</span>
                  <span className="text-theme-muted">Points:</span>
                  <span className="text-theme-primary">{selectedQuestion.points}</span>
                  {selectedQuestion.challenge_url && (
                    <>
                      <span className="text-theme-muted">Challenge URL:</span>
                      <span className="text-theme-primary font-mono break-all">{selectedQuestion.challenge_url}</span>
                    </>
                  )}
                  {selectedQuestion.expected_flag && (
                    <>
                      <span className="text-theme-muted">Expected flag:</span>
                      <span className="text-theme-primary font-mono break-all">{selectedQuestion.expected_flag}</span>
                    </>
                  )}
                </div>
                {selectedQuestion.dataset_json && (
                  <div className="mb-2">
                    <span className="text-theme-muted text-sm">Dataset:</span>
                    <pre className="text-xs text-theme-primary bg-theme-primary p-2 rounded mt-1 overflow-auto max-h-40 font-mono">
                      {JSON.stringify(selectedQuestion.dataset_json, null, 2)}
                    </pre>
                  </div>
                )}
                <div className="flex flex-wrap gap-1 mb-2">
                  {(selectedQuestion.domain_names || []).map((name, i) => (
                    <span key={i} className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">{name}</span>
                  ))}
                </div>
                <span className={`text-xs px-2 py-0.5 rounded ${selectedQuestion.is_active ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
                  {selectedQuestion.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>
            ) : (
              <div className="bg-theme-secondary rounded-lg p-12 text-center text-theme-muted">
                Select a challenge from the list or create a new one.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminHandsOn;
