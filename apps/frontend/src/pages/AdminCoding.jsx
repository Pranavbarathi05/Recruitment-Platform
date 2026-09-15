import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { generatePythonStarterCode } from '../utils/codingStarterCode';

/**
 * Admin Coding Problems Page — Function-Based Problem Builder
 *
 * Admin management for LeetCode-style coding problems.
 * Features:
 * - Create/edit/delete coding problems with function metadata
 * - Per-language starter code
 * - JSON test case management (arguments + expected output)
 * - Bulk test case upload
 * - Public/Hidden visibility
 */

const DIFFICULTIES = ['easy', 'medium', 'hard'];
const LANGUAGES = ['python3', 'cpp', 'java', 'c'];
const LANGUAGE_LABELS = { python3: 'Python 3', cpp: 'C++', java: 'Java', c: 'C' };

const AdminCoding = () => {
  const { getAuthHeaders } = useAuth();
  const navigate = useNavigate();

  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  // Problems state
  const [problems, setProblems] = useState([]);
  const [selectedProblem, setSelectedProblem] = useState(null);
  const [showProblemForm, setShowProblemForm] = useState(false);
  const [editingProblem, setEditingProblem] = useState(null);
  const [problemForm, setProblemForm] = useState({
    title: '', slug: '', description: '',
    difficulty: 'medium', constraints: '', points: 10,
    time_limit_ms: 2000, memory_limit_mb: 256,
    supported_languages: ['python3', 'cpp', 'java'], is_active: true,
    starter_code: { python3: '' },
    function_name: 'solve', class_name: '', function_signature: '',
    input_format: '', output_format: '', explanation: '',
  });

  // Test cases state
  const [testCases, setTestCases] = useState([]);
  const [showTestForm, setShowTestForm] = useState(false);
  const [editingTest, setEditingTest] = useState(null);
  const [testForm, setTestForm] = useState({
    arguments: '', expected_output: '',
    is_public: false, points: 1, ordering: 0,
  });

  // Bulk upload state
  const [showBulkUpload, setShowBulkUpload] = useState(false);
  const [bulkJson, setBulkJson] = useState('');
  const [bulkError, setBulkError] = useState('');

  const [message, setMessage] = useState('');
  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // Admin check
  useEffect(() => {
    

    // Cookie auth
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

  // Fetch problems
  const fetchProblems = useCallback(async () => {
    
    // Cookie auth
    try {
      const resp = await fetch(`${apiUrl}/admin/coding/problems`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setProblems(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Error fetching problems:', err);
    }
  }, [apiUrl]);

  // Fetch test cases
  const fetchTestCases = useCallback(async (problemId) => {
    
    // Cookie auth
    try {
      const resp = await fetch(`${apiUrl}/admin/coding/problems/${problemId}/tests`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setTestCases(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Error fetching tests:', err);
    }
  }, [apiUrl]);

  useEffect(() => {
    if (!isAdmin) return;
    // Cookie auth
    fetch(`${apiUrl}/admin/coding/problems`, { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => { if (Array.isArray(data)) setProblems(data); })
      .catch((err) => console.error('Error fetching problems:', err));
  }, [isAdmin, apiUrl]);

  useEffect(() => {
    if (!selectedProblem) return;
    // Cookie auth
    fetch(`${apiUrl}/admin/coding/problems/${selectedProblem.id}/tests`, { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => { if (Array.isArray(data)) setTestCases(data); })
      .catch((err) => console.error('Error fetching tests:', err));
  }, [selectedProblem, apiUrl]);

  // Problem CRUD
  const handleProblemSubmit = async (e) => {
    e.preventDefault();
    try {
      const url = editingProblem
        ? `${apiUrl}/admin/coding/problems/${editingProblem.id}`
        : `${apiUrl}/admin/coding/problems`;
      const method = editingProblem ? 'PUT' : 'POST';

      const payload = { ...problemForm };
      if (!editingProblem && !payload.slug) {
        payload.slug = payload.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      }

      // Cookie auth
      const resp = await fetch(url, {
        method,
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify(payload),
      });

      if (resp.ok) {
        setMessage(editingProblem ? 'Problem updated' : 'Problem created');
        setShowProblemForm(false);
        setEditingProblem(null);
        resetProblemForm();
        fetchProblems();
      } else {
        const err = await resp.json();
        setMessage(err.detail || 'Error saving problem');
      }
    } catch (err) {
      setMessage(err.message);
    }
  };

  const handleDeleteProblem = async (problemId) => {
    if (!confirm('Delete this problem? This cannot be undone.')) return;
    try {
      // Cookie auth
      const resp = await fetch(`${apiUrl}/admin/coding/problems/${problemId}`, {
        method: 'DELETE', headers: getAuthHeaders(), credentials: 'include',
      });
      if (resp.ok) {
        setMessage('Problem deleted');
        setSelectedProblem(null);
        fetchProblems();
      } else {
        const err = await resp.json();
        setMessage(err.detail || 'Error deleting problem');
      }
    } catch (err) {
      setMessage(err.message);
    }
  };

  const handleToggleProblemActive = async (problem) => {
    const endpoint = problem.is_active
      ? `${apiUrl}/admin/coding/problems/${problem.id}/deactivate`
      : `${apiUrl}/admin/coding/problems/${problem.id}/activate`;
    try {
      // Cookie auth
      const resp = await fetch(endpoint, { method: 'POST', headers: getAuthHeaders(), credentials: 'include' });
      if (resp.ok) {
        setMessage(problem.is_active ? 'Problem deactivated' : 'Problem activated');
        fetchProblems();
        if (selectedProblem?.id === problem.id) {
          setSelectedProblem({ ...selectedProblem, is_active: !problem.is_active });
        }
      }
    } catch (err) {
      setMessage(err.message);
    }
  };

  // Test Case CRUD
  const handleTestSubmit = async (e) => {
    e.preventDefault();
    try {
      // Parse JSON arguments
      let parsedArgs;
      let parsedExpected;
      try {
        parsedArgs = JSON.parse(testForm.arguments);
        if (!Array.isArray(parsedArgs)) {
          setMessage('Arguments must be a JSON array');
          return;
        }
      } catch {
        setMessage('Invalid JSON in arguments field');
        return;
      }
      try {
        parsedExpected = JSON.parse(testForm.expected_output);
      } catch {
        setMessage('Invalid JSON in expected output field');
        return;
      }

      const url = editingTest
        ? `${apiUrl}/admin/coding/tests/${editingTest.id}`
        : `${apiUrl}/admin/coding/problems/${selectedProblem.id}/tests`;
      const method = editingTest ? 'PUT' : 'POST';

      // Cookie auth
      const resp = await fetch(url, {
        method,
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({
          arguments: parsedArgs,
          expected_output: parsedExpected,
          is_public: testForm.is_public,
          points: testForm.points,
          ordering: testForm.ordering,
        }),
      });

      if (resp.ok) {
        setMessage(editingTest ? 'Test case updated' : 'Test case created');
        setShowTestForm(false);
        setEditingTest(null);
        setTestForm({ arguments: '', expected_output: '', is_public: false, points: 1, ordering: testCases.length });
        fetchTestCases(selectedProblem.id);
      } else {
        const err = await resp.json();
        setMessage(err.detail || 'Error saving test case');
      }
    } catch (err) {
      setMessage(err.message);
    }
  };

  const handleDeleteTest = async (testId) => {
    if (!confirm('Delete this test case?')) return;
    try {
      // Cookie auth
      const resp = await fetch(`${apiUrl}/admin/coding/tests/${testId}`, {
        method: 'DELETE', headers: getAuthHeaders(), credentials: 'include',
      });
      if (resp.ok) {
        setMessage('Test case deleted');
        fetchTestCases(selectedProblem.id);
      }
    } catch (err) {
      setMessage(err.message);
    }
  };

  // Bulk upload
  const handleBulkUpload = async () => {
    try {
      const parsed = JSON.parse(bulkJson);
      if (!Array.isArray(parsed)) {
        setBulkError('JSON must be an array of test cases');
        return;
      }

      // Validate each test case
      for (let i = 0; i < parsed.length; i++) {
        const tc = parsed[i];
        if (!tc.arguments || !Array.isArray(tc.arguments)) {
          setBulkError(`Test case ${i + 1}: arguments must be a JSON array`);
          return;
        }
        if (tc.expected_output === undefined) {
          setBulkError(`Test case ${i + 1}: expected_output is required`);
          return;
        }
      }

      // Cookie auth
      const resp = await fetch(`${apiUrl}/admin/coding/problems/${selectedProblem.id}/tests/bulk`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ test_cases: parsed }),
      });

      if (resp.ok) {
        const result = await resp.json();
        setMessage(`Uploaded ${result.count} test cases`);
        setShowBulkUpload(false);
        setBulkJson('');
        setBulkError('');
        fetchTestCases(selectedProblem.id);
      } else {
        const err = await resp.json();
        setBulkError(err.detail || 'Error uploading test cases');
      }
    } catch (err) {
      setBulkError('Invalid JSON: ' + err.message);
    }
  };

  const resetProblemForm = () => {
    setProblemForm({
      title: '', slug: '', description: '',
      difficulty: 'medium', constraints: '', points: 10,
      time_limit_ms: 2000, memory_limit_mb: 256,
      supported_languages: ['python3', 'cpp', 'java'], is_active: true,
      starter_code: { python3: '' },
      function_name: 'solve', class_name: '', function_signature: '',
      input_format: '', output_format: '', explanation: '',
    });
  };

  const startEditProblem = (problem) => {
    setEditingProblem(problem);
    setProblemForm({
      title: problem.title,
      slug: problem.slug,
      description: problem.description,
      difficulty: problem.difficulty,
      constraints: problem.constraints || '',
      points: problem.points,
      time_limit_ms: problem.time_limit_ms,
      memory_limit_mb: problem.memory_limit_mb,
      supported_languages: problem.supported_languages || ['python3'],
      is_active: problem.is_active,
      starter_code: problem.starter_code && Object.keys(problem.starter_code).length > 0
        ? problem.starter_code
        : { python3: '' },
      function_name: problem.function_name || 'solve',
      class_name: problem.class_name || '',
      function_signature: problem.function_signature || '',
      input_format: problem.input_format || '',
      output_format: problem.output_format || '',
      explanation: problem.explanation || '',
    });
    setShowProblemForm(true);
  };

  if (loading || !isAdmin) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-blue-500" />
      </div>
    );
  }

  const inputClass = 'w-full bg-theme-primary text-theme-primary border border-theme-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';
  const labelClass = 'block text-sm font-medium text-theme-muted mb-1';

  const updatePythonStarterCode = (value) => {
    setProblemForm({
      ...problemForm,
      starter_code: { ...problemForm.starter_code, python3: value },
    });
  };

  const applyPythonStarterFromMetadata = () => {
    try {
      const generated = generatePythonStarterCode(
        problemForm.function_name,
        problemForm.class_name,
        problemForm.function_signature,
      );
      updatePythonStarterCode(generated);
    } catch {
      updatePythonStarterCode('');
    }
  };

  return (
    <div className="min-h-screen bg-theme-primary py-8 px-4">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <button onClick={() => navigate('/admin')} className="text-theme-muted hover:text-theme-primary transition-colors">
            ← Back to Admin Panel
          </button>
          <h1 className="text-3xl font-bold text-theme-primary">Coding Problems</h1>
        </div>

        {message && (
          <div className="bg-blue-900/30 border border-blue-500 text-blue-300 px-4 py-3 rounded-lg mb-4 text-sm">
            {message}
            <button onClick={() => setMessage('')} className="ml-2 underline">dismiss</button>
          </div>
        )}

        <div className="flex gap-6">
          {/* Problems List */}
          <div className="w-1/2">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-theme-primary">Problems ({problems.length})</h2>
              <button
                onClick={() => { resetProblemForm(); setEditingProblem(null); setShowProblemForm(true); }}
                className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-semibold"
              >
                + New Problem
              </button>
            </div>

            {problems.length === 0 ? (
              <div className="bg-theme-secondary rounded-lg p-8 text-center text-theme-muted">
                No coding problems yet. Create your first problem to get started.
              </div>
            ) : (
              <div className="space-y-2">
                {problems.map((p) => (
                  <div
                    key={p.id}
                    className={`bg-theme-secondary rounded-lg p-4 cursor-pointer transition-colors ${
                      selectedProblem?.id === p.id ? 'ring-2 ring-blue-500' : 'hover:ring-1 hover:ring-theme-border'
                    }`}
                    onClick={() => setSelectedProblem(p)}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold text-theme-primary">{p.title}</h3>
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                            p.difficulty === 'easy' ? 'bg-green-900/50 text-green-300'
                              : p.difficulty === 'hard' ? 'bg-red-900/50 text-red-300'
                                : 'bg-yellow-900/50 text-yellow-300'
                          }`}>{p.difficulty}</span>
                          <span className={`px-2 py-0.5 rounded text-xs ${p.is_active ? 'bg-green-900/30 text-green-400' : 'bg-gray-700 text-gray-400'}`}>
                            {p.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                        <div className="text-xs text-theme-muted mt-1">
                          {p.function_name || 'solve'}() • {p.points} pts • {p.public_test_count}/{p.total_test_count} tests
                        </div>
                      </div>
                      <div className="flex gap-1">
                        <button onClick={(e) => { e.stopPropagation(); startEditProblem(p); }} className="text-blue-400 hover:text-blue-300 text-xs px-2">Edit</button>
                        <button onClick={(e) => { e.stopPropagation(); handleToggleProblemActive(p); }} className="text-yellow-400 hover:text-yellow-300 text-xs px-2">
                          {p.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); handleDeleteProblem(p.id); }} className="text-red-400 hover:text-red-300 text-xs px-2">Delete</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right panel */}
          <div className="w-1/2">
            {showProblemForm ? (
              <div className="bg-theme-secondary rounded-lg p-6 max-h-[80vh] overflow-y-auto">
                <h2 className="text-xl font-bold text-theme-primary mb-4">
                  {editingProblem ? 'Edit Problem' : 'New Problem'}
                </h2>
                <form onSubmit={handleProblemSubmit} className="space-y-3">
                  {/* Basic Info */}
                  <div className="border-b border-theme-border pb-3">
                    <h3 className="text-sm font-bold text-theme-primary mb-2">Problem Details</h3>
                    <div>
                      <label className={labelClass}>Title *</label>
                      <input value={problemForm.title} onChange={(e) => setProblemForm({ ...problemForm, title: e.target.value })} className={inputClass} required />
                    </div>
                    <div>
                      <label className={labelClass}>Slug *</label>
                      <input value={problemForm.slug} onChange={(e) => setProblemForm({ ...problemForm, slug: e.target.value })} className={inputClass} required />
                    </div>
                    <div>
                      <label className={labelClass}>Description *</label>
                      <textarea value={problemForm.description} onChange={(e) => setProblemForm({ ...problemForm, description: e.target.value })} className={inputClass} rows={4} required />
                    </div>
                    <div className="grid grid-cols-3 gap-3 mt-2">
                      <div>
                        <label className={labelClass}>Difficulty</label>
                        <select value={problemForm.difficulty} onChange={(e) => setProblemForm({ ...problemForm, difficulty: e.target.value })} className={inputClass}>
                          {DIFFICULTIES.map((d) => <option key={d} value={d}>{d}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className={labelClass}>Points</label>
                        <input type="number" value={problemForm.points} onChange={(e) => setProblemForm({ ...problemForm, points: parseInt(e.target.value) || 10 })} className={inputClass} min={1} />
                      </div>
                      <div>
                        <label className={labelClass}>Time Limit (ms)</label>
                        <input type="number" value={problemForm.time_limit_ms} onChange={(e) => setProblemForm({ ...problemForm, time_limit_ms: parseInt(e.target.value) || 2000 })} className={inputClass} min={100} />
                      </div>
                    </div>
                    <div>
                      <label className={labelClass}>Constraints</label>
                      <textarea value={problemForm.constraints} onChange={(e) => setProblemForm({ ...problemForm, constraints: e.target.value })} className={inputClass} rows={2} />
                    </div>
                  </div>

                  {/* Function Definition */}
                  <div className="border-b border-theme-border pb-3">
                    <h3 className="text-sm font-bold text-theme-primary mb-2">Function Definition</h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className={labelClass}>Function Name *</label>
                        <input value={problemForm.function_name} onChange={(e) => setProblemForm({ ...problemForm, function_name: e.target.value })} className={inputClass} required />
                      </div>
                      <div>
                        <label className={labelClass}>Class Name</label>
                        <input value={problemForm.class_name} onChange={(e) => setProblemForm({ ...problemForm, class_name: e.target.value })} className={inputClass} placeholder="e.g. Solution" />
                      </div>
                    </div>
                    <div>
                      <label className={labelClass}>Function Signature</label>
                      <input value={problemForm.function_signature} onChange={(e) => setProblemForm({ ...problemForm, function_signature: e.target.value })} className={inputClass} placeholder="e.g. def twoSum(self, nums: List[int], target: int) -> List[int]" />
                    </div>
                    <p className="text-xs text-theme-muted mt-1">
                      These fields describe the function contract. The Python starter below is the candidate-visible
                      boilerplate; the test harness and invocation code stay behind the scenes.
                    </p>

                    {/* Supported Languages (per-problem opt-in) */}
                    <div className="mt-3">
                      <label className={labelClass}>Supported Languages</label>
                      <div className="flex flex-wrap gap-4 mt-1">
                        {LANGUAGES.map((lang) => (
                          <label key={lang} className="flex items-center gap-2 text-sm text-theme-primary">
                            <input
                              type="checkbox"
                              checked={problemForm.supported_languages.includes(lang)}
                              onChange={(e) => setProblemForm({
                                ...problemForm,
                                supported_languages: e.target.checked
                                  ? [...problemForm.supported_languages, lang]
                                  : problemForm.supported_languages.filter((l) => l !== lang),
                              })}
                              className="rounded"
                            />
                            {LANGUAGE_LABELS[lang] || lang}
                          </label>
                        ))}
                      </div>
                      <p className="text-xs text-theme-muted mt-1">
                        C runs server-side only and requires an explicit C function_signature
                        (e.g. "int add(int a, int b)"); supported C types: int, long long, double, bool,
                        plus the in-place array pattern "int f(int* nums, int numsSize)" — the array
                        length is derived from the JSON test argument, and an expected_output of
                        {"{"}"returns: k, mutated: [prefix]{"}"} additionally verifies the mutated array prefix.
                        The shared function_signature field may hold C syntax: C++/Java automatically
                        ignore C-style signatures and fall back to type inference from the test cases.
                      </p>
                    </div>
                  </div>

                  {/* Starter Code (per language) */}
                  <div className="border-b border-theme-border pb-3">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-bold text-theme-primary mb-0">Starter Code (per language)</h3>
                      <button
                        type="button"
                        onClick={applyPythonStarterFromMetadata}
                        className="text-xs text-blue-400 hover:text-blue-300 underline"
                      >
                        Regenerate Python from metadata
                      </button>
                    </div>
                    {LANGUAGES.filter((l) => problemForm.supported_languages.includes(l)).map((lang) => (
                      <div key={lang} className="mb-2">
                        <label className={labelClass}>{LANGUAGE_LABELS[lang] || lang} {lang === 'python3' ? '(candidate-visible)' : ''}</label>
                        <textarea
                          value={problemForm.starter_code?.[lang] || ''}
                          onChange={(e) => setProblemForm({
                            ...problemForm,
                            starter_code: { ...problemForm.starter_code, [lang]: e.target.value },
                          })}
                          className={`${inputClass} font-mono text-xs`}
                          rows={6}
                          placeholder={lang === 'python3' ? 'Generated from function metadata when you click "Regenerate".' : 'Candidate-visible starter code for this language.'}
                        />
                      </div>
                    ))}
                  </div>

                  <div className="flex gap-2">
                    <button type="submit" className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-semibold">
                      {editingProblem ? 'Update' : 'Create'}
                    </button>
                    <button type="button" onClick={() => { setShowProblemForm(false); setEditingProblem(null); }} className="bg-theme-tertiary text-theme-muted px-4 py-2 rounded-lg text-sm">
                      Cancel
                    </button>
                  </div>
                </form>
              </div>
            ) : selectedProblem ? (
              <div className="bg-theme-secondary rounded-lg p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-bold text-theme-primary">{selectedProblem.title}</h2>
                  <div className="flex gap-2">
                    <button
                      onClick={() => { setShowBulkUpload(!showBulkUpload); }}
                      className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded-lg text-sm font-semibold"
                    >
                      📦 Bulk Upload
                    </button>
                    <button
                      onClick={() => { setTestForm({ arguments: '', expected_output: '', is_public: false, points: 1, ordering: testCases.length }); setEditingTest(null); setShowTestForm(true); }}
                      className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg text-sm font-semibold"
                    >
                      + Add Test Case
                    </button>
                  </div>
                </div>

                {/* Bulk Upload */}
                {showBulkUpload && (
                  <div className="bg-theme-primary rounded-lg p-4 mb-4 space-y-3">
                    <h3 className="font-semibold text-theme-primary text-sm">Bulk Upload (JSON)</h3>
                    <p className="text-xs text-theme-muted">
                      Paste a JSON array of test cases. Each object needs: arguments (array), expected_output (any JSON), is_public (bool), points (int).
                    </p>
                    <textarea
                      value={bulkJson}
                      onChange={(e) => setBulkJson(e.target.value)}
                      className={`${inputClass} font-mono text-xs`}
                      rows={8}
                      placeholder='[{"arguments": [[2,7,11,15], 9], "expected_output": [0,1], "is_public": true, "points": 1}]'
                    />
                    {bulkError && <div className="text-red-400 text-xs">{bulkError}</div>}
                    <div className="flex gap-2">
                      <button onClick={handleBulkUpload} className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded text-sm">
                        Upload
                      </button>
                      <button onClick={() => { setShowBulkUpload(false); setBulkJson(''); setBulkError(''); }} className="text-theme-muted text-sm">
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {/* Test Case Form */}
                {showTestForm && (
                  <form onSubmit={handleTestSubmit} className="bg-theme-primary rounded-lg p-4 mb-4 space-y-3">
                    <h3 className="font-semibold text-theme-primary text-sm">{editingTest ? 'Edit Test Case' : 'New Test Case'}</h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className={labelClass}>Arguments (JSON array) *</label>
                        <textarea
                          value={testForm.arguments}
                          onChange={(e) => setTestForm({ ...testForm, arguments: e.target.value })}
                          className={`${inputClass} font-mono text-xs`}
                          rows={3}
                          placeholder='[[2,7,11,15], 9]'
                          required
                        />
                      </div>
                      <div>
                        <label className={labelClass}>Expected Output (JSON) *</label>
                        <textarea
                          value={testForm.expected_output}
                          onChange={(e) => setTestForm({ ...testForm, expected_output: e.target.value })}
                          className={`${inputClass} font-mono text-xs`}
                          rows={3}
                          placeholder='[0,1]'
                          required
                        />
                        <p className="text-xs text-theme-muted mt-1">
                          C in-place array problems: use {'{'}"returns": k, "mutated": [prefix]{'}'} to also
                          verify the first k elements after the call (e.g. {'{'}"returns": 2, "mutated": [1,2]{'}'}).
                        </p>
                      </div>
                    </div>
                    <div className="flex gap-3 items-end">
                      <div className="flex items-center gap-2">
                        <input type="checkbox" id="is_public" checked={testForm.is_public} onChange={(e) => setTestForm({ ...testForm, is_public: e.target.checked })} className="rounded" />
                        <label htmlFor="is_public" className="text-sm text-theme-primary">Public</label>
                      </div>
                      <div>
                        <label className={labelClass}>Points</label>
                        <input type="number" value={testForm.points} onChange={(e) => setTestForm({ ...testForm, points: parseInt(e.target.value) || 1 })} className="w-20 bg-theme-secondary text-theme-primary border border-theme-border rounded px-2 py-1 text-sm" min={1} />
                      </div>
                      <div>
                        <label className={labelClass}>Order</label>
                        <input type="number" value={testForm.ordering} onChange={(e) => setTestForm({ ...testForm, ordering: parseInt(e.target.value) || 0 })} className="w-20 bg-theme-secondary text-theme-primary border border-theme-border rounded px-2 py-1 text-sm" min={0} />
                      </div>
                      <button type="submit" className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded text-sm">
                        {editingTest ? 'Update' : 'Add'}
                      </button>
                      <button type="button" onClick={() => { setShowTestForm(false); setEditingTest(null); }} className="text-theme-muted text-sm">Cancel</button>
                    </div>
                  </form>
                )}

                {/* Test Cases List */}
                {testCases.length === 0 ? (
                  <div className="text-theme-muted text-sm py-4">No test cases yet. Add your first test case above.</div>
                ) : (
                  <div className="space-y-2">
                    {testCases.map((tc, idx) => (
                      <div key={tc.id} className={`rounded-lg p-3 text-sm ${tc.is_public ? 'bg-blue-900/20 border border-blue-800' : 'bg-purple-900/20 border border-purple-800'}`}>
                        <div className="flex items-center justify-between mb-1">
                          <span className={`text-xs font-bold ${tc.is_public ? 'text-blue-400' : 'text-purple-400'}`}>
                            {tc.is_public ? '🌐 PUBLIC' : '🔒 HIDDEN'} — Test {idx + 1} ({tc.points} pts)
                          </span>
                          <div className="flex gap-1">
                            <button onClick={() => {
                              setTestForm({
                                arguments: tc.arguments ? JSON.stringify(tc.arguments, null, 2) : tc.input || '',
                                expected_output: tc.expected_output !== undefined ? JSON.stringify(tc.expected_output, null, 2) : '',
                                is_public: tc.is_public, points: tc.points, ordering: tc.ordering,
                              });
                              setEditingTest(tc);
                              setShowTestForm(true);
                            }} className="text-blue-400 hover:text-blue-300 text-xs">Edit</button>
                            <button onClick={() => handleDeleteTest(tc.id)} className="text-red-400 hover:text-red-300 text-xs">Delete</button>
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-2 font-mono text-xs">
                          <div>
                            <span className="text-theme-muted">Arguments:</span>
                            <pre className="text-theme-secondary bg-theme-primary rounded p-2 mt-1 whitespace-pre-wrap max-h-20 overflow-y-auto">
                              {tc.arguments ? JSON.stringify(tc.arguments, null, 2) : tc.input}
                            </pre>
                          </div>
                          <div>
                            <span className="text-theme-muted">Expected:</span>
                            <pre className="text-theme-secondary bg-theme-primary rounded p-2 mt-1 whitespace-pre-wrap max-h-20 overflow-y-auto">
                              {tc.expected_output !== undefined ? JSON.stringify(tc.expected_output, null, 2) : ''}
                            </pre>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-theme-secondary rounded-lg p-8 text-center text-theme-muted">
                Select a coding problem to manage its test cases.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminCoding;
