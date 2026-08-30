import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * Admin Panel
 *
 * Admin functionality for managing domains and MCQ question banks.
 * Only accessible to users with is_admin = true in profiles.
 *
 * Features:
 * - Domain CRUD (create, edit, activate/deactivate)
 * - Per-semester MCQ counts on domain list
 * - MCQ CRUD with semester filter
 * - MCQ activate/deactivate and safe delete
 */
const SEMESTERS = [
  { value: 1, label: '1st Semester' },
  { value: 3, label: '3rd Semester' },
  { value: 5, label: '5th Semester' },
  { value: 7, label: '7th Semester' },
];

const AdminPanel = () => {
  const { session } = useAuth();
  const navigate = useNavigate();

  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [domains, setDomains] = useState([]);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [mcqs, setMcqs] = useState([]);
  const [semesterFilter, setSemesterFilter] = useState(null); // null = all

  // Domain form state
  const [showDomainForm, setShowDomainForm] = useState(false);
  const [editingDomain, setEditingDomain] = useState(null);
  const [domainForm, setDomainForm] = useState({ name: '', slug: '', description: '', duration_minutes: 20, is_active: true });

  // MCQ form state
  const [showMcqForm, setShowMcqForm] = useState(false);
  const [editingMcq, setEditingMcq] = useState(null);
  const [mcqForm, setMcqForm] = useState({
    question_text: '', option_a: '', option_b: '', option_c: '', option_d: '',
    correct_option: 'A', explanation: '', is_active: true, semester: 1,
  });

  const [message, setMessage] = useState('');
  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // Memoize auth headers so the effect dependency is stable
  const authHeaders = useMemo(
    () => session?.access_token
      ? { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` }
      : null,
    [session?.access_token],
  );

  // Check admin status on mount and whenever session changes
  useEffect(() => {
    if (!authHeaders) return;

    let cancelled = false;

    const checkAdmin = async () => {
      try {
        const resp = await fetch(`${apiUrl}/admin/domains`, { headers: authHeaders });
        if (cancelled) return;

        if (resp.ok) {
          setIsAdmin(true);
        } else if (resp.status === 403) {
          // Explicitly not admin — redirect
          navigate('/domains');
        } else if (resp.status === 401) {
          // Token expired or invalid — let ProtectedRoute handle it
          navigate('/login');
        } else {
          // Server error — show message, don't redirect
          setMessage('Error: Could not verify admin status. Please try again.');
        }
      } catch {
        if (!cancelled) {
          setMessage('Error: Could not connect to the server.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    checkAdmin();
    return () => { cancelled = true; };
  }, [authHeaders, apiUrl, navigate]);

  // Fetch domains
  const fetchDomains = useCallback(async () => {
    try {
      const resp = await fetch(`${apiUrl}/admin/domains`, { headers: authHeaders });
      if (resp.ok) setDomains(await resp.json());
    } catch (err) {
      console.error(err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiUrl, session]);

  useEffect(() => {
    if (isAdmin) fetchDomains();
  }, [isAdmin, fetchDomains]);

  // Fetch MCQs for a domain, with optional semester filter
  const fetchMcqs = useCallback(async (domainId, sem) => {
    try {
      let url = `${apiUrl}/admin/domains/${domainId}/mcqs`;
      if (sem !== null && sem !== undefined) {
        url += `?semester=${sem}`;
      }
      const resp = await fetch(url, { headers: authHeaders });
      if (resp.ok) setMcqs(await resp.json());
    } catch (err) {
      console.error(err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiUrl, session]);

  // Re-fetch MCQs when semester filter changes
  useEffect(() => {
    if (selectedDomain) {
      fetchMcqs(selectedDomain.id, semesterFilter);
    }
  }, [semesterFilter, selectedDomain, fetchMcqs]);

  // Domain CRUD
  const handleDomainSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    try {
      const url = editingDomain
        ? `${apiUrl}/admin/domains/${editingDomain.id}`
        : `${apiUrl}/admin/domains`;
      const resp = await fetch(url, {
        method: editingDomain ? 'PUT' : 'POST',
        headers: authHeaders,
        body: JSON.stringify(domainForm),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail);
      }
      setMessage(editingDomain ? 'Domain updated' : 'Domain created');
      setShowDomainForm(false);
      setEditingDomain(null);
      setDomainForm({ name: '', slug: '', description: '', duration_minutes: 20, is_active: true });
      fetchDomains();
    } catch (err) {
      setMessage(`Error: ${err.message}`);
    }
  };

  const handleToggleDomain = async (domain) => {
    try {
      const action = domain.is_active ? 'deactivate' : 'activate';
      await fetch(`${apiUrl}/admin/domains/${domain.id}/${action}`, {
        method: 'POST',
        headers: authHeaders,
      });
      fetchDomains();
    } catch (err) {
      console.error(err);
    }
  };

  // MCQ CRUD
  const handleMcqSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    try {
      const url = editingMcq
        ? `${apiUrl}/admin/mcqs/${editingMcq.id}`
        : `${apiUrl}/admin/domains/${selectedDomain.id}/mcqs`;
      const resp = await fetch(url, {
        method: editingMcq ? 'PUT' : 'POST',
        headers: authHeaders,
        body: JSON.stringify(editingMcq ? mcqForm : { ...mcqForm, domain_id: selectedDomain.id }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail);
      }
      setMessage(editingMcq ? 'MCQ updated' : 'MCQ created');
      setShowMcqForm(false);
      setEditingMcq(null);
      setMcqForm({ question_text: '', option_a: '', option_b: '', option_c: '', option_d: '', correct_option: 'A', explanation: '', is_active: true, semester: 1 });
      fetchMcqs(selectedDomain.id, semesterFilter);
    } catch (err) {
      setMessage(`Error: ${err.message}`);
    }
  };

  const handleToggleMcq = async (mcq) => {
    try {
      const action = mcq.is_active ? 'deactivate' : 'activate';
      await fetch(`${apiUrl}/admin/mcqs/${mcq.id}/${action}`, {
        method: 'POST',
        headers: authHeaders,
      });
      fetchMcqs(selectedDomain.id, semesterFilter);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteMcq = async (mcqId) => {
    if (!confirm('Delete this MCQ? This cannot be undone if the question has been used in an attempt.')) return;
    try {
      const resp = await fetch(`${apiUrl}/admin/mcqs/${mcqId}`, { method: 'DELETE', headers: authHeaders });
      if (!resp.ok) {
        const err = await resp.json();
        setMessage(`Error: ${err.detail}`);
      } else {
        setMessage('MCQ deleted');
      }
      fetchMcqs(selectedDomain.id, semesterFilter);
    } catch (err) {
      console.error(err);
    }
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
        <h1 className="text-3xl font-bold text-theme-primary mb-8">Admin Panel</h1>

        {message && (
          <div className={`mb-4 p-3 rounded-lg text-sm ${message.startsWith('Error') ? 'bg-red-900/30 border border-red-500 text-red-300' : 'bg-green-900/30 border border-green-500 text-green-300'}`}>
            {message}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Domains List */}
          <div className="lg:col-span-1">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold text-theme-primary">Domains</h2>
              <button
                onClick={() => { setShowDomainForm(true); setEditingDomain(null); setDomainForm({ name: '', slug: '', description: '', duration_minutes: 20, is_active: true }); }}
                className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm"
              >
                + Add
              </button>
            </div>

            {showDomainForm && (
              <form onSubmit={handleDomainSubmit} className="bg-theme-secondary rounded-lg p-4 mb-4 space-y-3">
                <input placeholder="Name" value={domainForm.name} onChange={(e) => setDomainForm({ ...domainForm, name: e.target.value })} required className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm" />
                <input placeholder="Slug" value={domainForm.slug} onChange={(e) => setDomainForm({ ...domainForm, slug: e.target.value })} required className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm" />
                <input placeholder="Description" value={domainForm.description} onChange={(e) => setDomainForm({ ...domainForm, description: e.target.value })} className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm" />
                <input type="number" placeholder="Duration (min)" value={domainForm.duration_minutes} onChange={(e) => setDomainForm({ ...domainForm, duration_minutes: parseInt(e.target.value) || 20 })} className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm" />
                <div className="flex gap-2">
                  <button type="submit" className="flex-1 px-3 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm">{editingDomain ? 'Update' : 'Create'}</button>
                  <button type="button" onClick={() => { setShowDomainForm(false); setEditingDomain(null); }} className="px-3 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded text-sm">Cancel</button>
                </div>
              </form>
            )}

            <div className="space-y-2">
              {domains.map((d) => (
                <div
                  key={d.id}
                  onClick={() => { setSelectedDomain(d); setSemesterFilter(null); fetchMcqs(d.id, null); }}
                  className={`bg-theme-secondary rounded-lg p-3 cursor-pointer transition-all ${selectedDomain?.id === d.id ? 'ring-2 ring-blue-500' : 'hover:bg-theme-tertiary'}`}
                >
                  <div className="flex justify-between items-start">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-theme-primary truncate">{d.name}</h3>
                      {d.description && (
                        <p className="text-xs text-theme-muted truncate">{d.description}</p>
                      )}
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded ml-2 flex-shrink-0 ${d.is_active ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
                      {d.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>

                  {/* Per-semester MCQ counts */}
                  <div className="grid grid-cols-4 gap-1 mt-2 text-xs text-theme-muted">
                    {SEMESTERS.map((s) => (
                      <span key={s.value}>
                        {s.value}st: {d.semesterCounts?.[String(s.value)] ?? 0}
                      </span>
                    ))}
                  </div>

                  <div className="flex gap-1 mt-2">
                    <button onClick={(e) => { e.stopPropagation(); setEditingDomain(d); setDomainForm({ name: d.name, slug: d.slug, description: d.description || '', duration_minutes: d.duration_minutes, is_active: d.is_active }); setShowDomainForm(true); }} className="text-xs px-2 py-1 bg-blue-600 text-white rounded">Edit</button>
                    <button onClick={(e) => { e.stopPropagation(); handleToggleDomain(d); }} className="text-xs px-2 py-1 bg-yellow-600 text-white rounded">{d.is_active ? 'Deactivate' : 'Activate'}</button>
                  </div>
                </div>
              ))}
              {domains.length === 0 && (
                <p className="text-theme-muted text-center py-8">No domains yet. Create one to get started.</p>
              )}
            </div>
          </div>

          {/* MCQs for selected domain */}
          <div className="lg:col-span-2">
            {selectedDomain ? (
              <>
                <div className="mb-4">
                  <h2 className="text-xl font-bold text-theme-primary">MCQs — {selectedDomain.name}</h2>
                  {selectedDomain.description && (
                    <p className="text-sm text-theme-muted mt-1">{selectedDomain.description}</p>
                  )}
                </div>

                {/* Semester filter tabs */}
                <div className="flex gap-2 mb-4 flex-wrap">
                  <button
                    onClick={() => setSemesterFilter(null)}
                    className={`px-3 py-1 rounded text-sm ${semesterFilter === null ? 'bg-blue-600 text-white' : 'bg-theme-secondary text-theme-muted hover:text-theme-primary'}`}
                  >
                    All
                  </button>
                  {SEMESTERS.map((s) => (
                    <button
                      key={s.value}
                      onClick={() => setSemesterFilter(s.value)}
                      className={`px-3 py-1 rounded text-sm ${semesterFilter === s.value ? 'bg-blue-600 text-white' : 'bg-theme-secondary text-theme-muted hover:text-theme-primary'}`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>

                <div className="flex justify-end mb-4">
                  <button
                    onClick={() => { setShowMcqForm(true); setEditingMcq(null); setMcqForm({ question_text: '', option_a: '', option_b: '', option_c: '', option_d: '', correct_option: 'A', explanation: '', is_active: true, semester: semesterFilter || 1 }); }}
                    className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm"
                  >
                    + Add MCQ
                  </button>
                </div>

                {showMcqForm && (
                  <form onSubmit={handleMcqSubmit} className="bg-theme-secondary rounded-lg p-4 mb-4 space-y-3">
                    <textarea
                      placeholder="Question text"
                      value={mcqForm.question_text}
                      onChange={(e) => setMcqForm({ ...mcqForm, question_text: e.target.value })}
                      required
                      rows={3}
                      className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    />
                    <select
                      value={mcqForm.semester}
                      onChange={(e) => setMcqForm({ ...mcqForm, semester: parseInt(e.target.value) })}
                      className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    >
                      {SEMESTERS.map((s) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                    <div className="grid grid-cols-2 gap-3">
                      <input placeholder="Option A" value={mcqForm.option_a} onChange={(e) => setMcqForm({ ...mcqForm, option_a: e.target.value })} required className="px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm" />
                      <input placeholder="Option B" value={mcqForm.option_b} onChange={(e) => setMcqForm({ ...mcqForm, option_b: e.target.value })} required className="px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm" />
                      <input placeholder="Option C" value={mcqForm.option_c} onChange={(e) => setMcqForm({ ...mcqForm, option_c: e.target.value })} required className="px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm" />
                      <input placeholder="Option D" value={mcqForm.option_d} onChange={(e) => setMcqForm({ ...mcqForm, option_d: e.target.value })} required className="px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm" />
                    </div>
                    <select
                      value={mcqForm.correct_option}
                      onChange={(e) => setMcqForm({ ...mcqForm, correct_option: e.target.value })}
                      className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    >
                      <option value="A">Correct: A</option>
                      <option value="B">Correct: B</option>
                      <option value="C">Correct: C</option>
                      <option value="D">Correct: D</option>
                    </select>
                    <textarea
                      placeholder="Explanation (optional)"
                      value={mcqForm.explanation}
                      onChange={(e) => setMcqForm({ ...mcqForm, explanation: e.target.value })}
                      rows={2}
                      className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    />
                    <div className="flex gap-2">
                      <button type="submit" className="flex-1 px-3 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm">{editingMcq ? 'Update' : 'Create'}</button>
                      <button type="button" onClick={() => { setShowMcqForm(false); setEditingMcq(null); }} className="px-3 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded text-sm">Cancel</button>
                    </div>
                  </form>
                )}

                <div className="space-y-3">
                  {mcqs.map((mcq) => (
                    <div key={mcq.id} className="bg-theme-secondary rounded-lg p-4">
                      <div className="flex justify-between items-start mb-2">
                        <p className="text-theme-primary font-medium flex-1 mr-4">{mcq.question_text}</p>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <span className="text-xs text-theme-muted">Sem {mcq.semester}</span>
                          <span className={`text-xs px-2 py-0.5 rounded ${mcq.is_active ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
                            {mcq.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-1 text-xs text-theme-muted mb-2">
                        <span>A. {mcq.option_a}</span>
                        <span>B. {mcq.option_b}</span>
                        <span>C. {mcq.option_c}</span>
                        <span>D. {mcq.option_d}</span>
                      </div>
                      <p className="text-xs text-green-400 mb-1">Correct: {mcq.correct_option}</p>
                      {mcq.explanation && (
                        <p className="text-xs text-blue-400 mb-2 italic">Explanation: {mcq.explanation}</p>
                      )}
                      <div className="flex gap-1">
                        <button
                          onClick={() => {
                            setEditingMcq(mcq);
                            setMcqForm({
                              question_text: mcq.question_text,
                              option_a: mcq.option_a,
                              option_b: mcq.option_b,
                              option_c: mcq.option_c,
                              option_d: mcq.option_d,
                              correct_option: mcq.correct_option,
                              explanation: mcq.explanation || '',
                              is_active: mcq.is_active,
                              semester: mcq.semester || 1,
                            });
                            setShowMcqForm(true);
                          }}
                          className="text-xs px-2 py-1 bg-blue-600 text-white rounded"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => handleToggleMcq(mcq)}
                          className="text-xs px-2 py-1 bg-yellow-600 text-white rounded"
                        >
                          {mcq.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                        <button
                          onClick={() => handleDeleteMcq(mcq.id)}
                          className="text-xs px-2 py-1 bg-red-600 text-white rounded"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                  {mcqs.length === 0 && (
                    <div className="text-center py-12">
                      <p className="text-theme-muted">
                        {semesterFilter
                          ? `No MCQs for ${SEMESTERS.find((s) => s.value === semesterFilter)?.label || 'this semester'}.`
                          : 'No MCQs yet. Add some questions to this domain.'}
                      </p>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="text-center py-20">
                <p className="text-theme-secondary text-lg">Select a domain to manage its MCQs</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminPanel;
