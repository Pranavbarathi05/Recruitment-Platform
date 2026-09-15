import { useState, useEffect, useCallback } from 'react';
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
  const { getAuthHeaders } = useAuth();
  const navigate = useNavigate();

  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [domains, setDomains] = useState([]);
  const [selectedDomain, setSelectedDomain] = useState(null);
  const [mcqs, setMcqs] = useState([]);
  const [semesterFilter, setSemesterFilter] = useState(null); // null = all

  // Assessment config state
  const [configs, setConfigs] = useState([]);
  const [editingConfig, setEditingConfig] = useState(null);
  const [configForm, setConfigForm] = useState({});
  const [configError, setConfigError] = useState('');

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

  // Assessment Responses state
  const [submissions, setSubmissions] = useState([]);
  const [submissionsLoading, setSubmissionsLoading] = useState(false);
  const [subSearch, setSubSearch] = useState('');
  const [subSort, setSubSort] = useState('score');
  const [subOrder, setSubOrder] = useState('desc');
  const [subSemester, setSubSemester] = useState(null);
  const [subBranch, setSubBranch] = useState('');

  // Reset confirmation state
  const [resetCandidate, setResetCandidate] = useState(null);
  const [resetLoading, setResetLoading] = useState(false);

  // Admin remark state (one per attempt, chat button in submissions table)
  const [remarkTarget, setRemarkTarget] = useState(null); // submission row
  const [remarkText, setRemarkText] = useState('');
  const [remarkError, setRemarkError] = useState('');
  const [remarkSaving, setRemarkSaving] = useState(false);

  // Delete confirmation state
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // Reset All confirmation state
  const [showResetAll, setShowResetAll] = useState(false);
  const [resetAllLoading, setResetAllLoading] = useState(false);

  // Delete All confirmation state
  const [showDeleteAll, setShowDeleteAll] = useState(false);
  const [deleteAllLoading, setDeleteAllLoading] = useState(false);
  const [deleteAllConfirmText, setDeleteAllConfirmText] = useState('');

  const [message, setMessage] = useState('');
  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // Memoize auth headers so the effect dependency is stable
  // Cookie auth — no manual auth headers needed

  // Fetch assessment configs
  const fetchConfigs = useCallback(async () => {
    // Cookie auth — always available
    try {
      const resp = await fetch(`${apiUrl}/admin/config`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setConfigs(Array.isArray(data) ? data : []);
      } else {
        console.error('Failed to fetch configs:', resp.status, resp.statusText);
        setConfigs([]);
      }
    } catch (err) {
      console.error('Error fetching configs:', err);
      setConfigs([]);
    }
  }, [apiUrl]);

  useEffect(() => {
    if (isAdmin) fetchConfigs();
  }, [isAdmin, fetchConfigs]);

  // Fetch submissions list
  const fetchSubmissions = useCallback(async () => {
    // Cookie auth — always available
    try {
      setSubmissionsLoading(true);
      const params = new URLSearchParams();
      if (subSort) params.set('sort', subSort);
      if (subOrder) params.set('order', subOrder);
      if (subSemester) params.set('semester', subSemester);
      if (subBranch) params.set('branch', subBranch);

      if (subSearch) params.set('search', subSearch);

      const resp = await fetch(`${apiUrl}/admin/assessments/submissions?${params}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setSubmissions(Array.isArray(data) ? data : []);
      } else {
        console.error('Failed to fetch submissions:', resp.status);
        setSubmissions([]);
      }
    } catch (err) {
      console.error('Error fetching submissions:', err);
      setSubmissions([]);
    } finally {
      setSubmissionsLoading(false);
    }
  }, [apiUrl, subSort, subOrder, subSemester, subBranch, subSearch]);

  useEffect(() => {
    if (isAdmin) fetchSubmissions();
  }, [isAdmin, fetchSubmissions]);

  // Config CRUD
  const handleConfigSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    setConfigError('');

    // Client-side validation before sending to backend
    const tq = configForm.total_questions;
    const cc = configForm.coding_problem_count;
    const md = configForm.max_domains;

    if (tq !== undefined && tq !== null && tq < 1) {
      setConfigError('MCQ questions must be at least 1.');
      return;
    }
    if (cc !== undefined && cc !== null && cc < 0) {
      setConfigError('Coding problems cannot be negative.');
      return;
    }
    if (md !== undefined && md !== null && (md < 1 || md > 2)) {
      setConfigError('Maximum domains must be 1 or 2.');
      return;
    }
    if (md === 2 && tq !== undefined && tq !== null && tq % 2 !== 0) {
      setConfigError('MCQ questions must be even when using 2 domains.');
      return;
    }
    if (md === 2 && cc !== undefined && cc !== null && cc > 0 && cc % 2 !== 0) {
      setConfigError('Coding problems must be even when using 2 domains.');
      return;
    }
    const dc = configForm.descriptive_question_count;
    if (dc !== undefined && dc !== null && dc < 0) {
      setConfigError('Descriptive questions cannot be negative.');
      return;
    }

    try {
      // Filter out undefined values so we only send changed fields
      const payload = Object.fromEntries(
        Object.entries(configForm).filter(([, v]) => v !== undefined && v !== null)
      );
      const resp = await fetch(`${apiUrl}/admin/config/${editingConfig.id}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify(payload),
        credentials: 'include',
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail);
      }
      setMessage('Configuration updated');
      setEditingConfig(null);
      setConfigForm({});
      setConfigError('');
      fetchConfigs();
    } catch (err) {
      setMessage(`Error: ${err.message}`);
    }
  };

  // Check admin status on mount and whenever session changes
  useEffect(() => {
    // Cookie auth — always available

    let cancelled = false;

    const checkAdmin = async () => {
      try {
        const resp = await fetch(`${apiUrl}/admin/domains`, { credentials: 'include' });
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
  }, [apiUrl, navigate]);

  // Fetch domains
  const fetchDomains = useCallback(async () => {
    // Cookie auth — always available
    try {
      const resp = await fetch(`${apiUrl}/admin/domains`, { credentials: 'include' });
      if (resp.ok) setDomains(await resp.json());
    } catch (err) {
      console.error(err);
    }
  }, [apiUrl]);

  useEffect(() => {
    if (isAdmin) fetchDomains();
  }, [isAdmin, fetchDomains]);

  // Fetch MCQs for a domain, with optional semester filter
  const fetchMcqs = useCallback(async (domainId, sem) => {
    // Cookie auth — always available
    try {
      let url = `${apiUrl}/admin/domains/${domainId}/mcqs`;
      if (sem !== null && sem !== undefined) {
        url += `?semester=${sem}`;
      }
      const resp = await fetch(url, { credentials: 'include' });
      if (resp.ok) setMcqs(await resp.json());
    } catch (err) {
      console.error(err);
    }
  }, [apiUrl]);

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
        headers: getAuthHeaders(),
        body: JSON.stringify(domainForm),
        credentials: 'include',
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
        headers: getAuthHeaders(),
        credentials: 'include',
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
        headers: getAuthHeaders(),
        body: JSON.stringify(editingMcq ? mcqForm : { ...mcqForm, domain_id: selectedDomain.id }),
        credentials: 'include',
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
        headers: getAuthHeaders(),
        credentials: 'include',
      });
      fetchMcqs(selectedDomain.id, semesterFilter);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteMcq = async (mcqId) => {
    if (!confirm('Delete this MCQ? This cannot be undone if the question has been used in an attempt.')) return;
    try {
      const resp = await fetch(`${apiUrl}/admin/mcqs/${mcqId}`, { method: 'DELETE', headers: getAuthHeaders(), credentials: 'include' });
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

  // Reset assessment handler
  const handleResetAssessment = async () => {
    if (!resetCandidate || resetLoading) return;
    setResetLoading(true);
    try {
      const resp = await fetch(`${apiUrl}/admin/assessments/${resetCandidate.attempt_id}/reset`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Reset failed');
      }
      setMessage(`Assessment reset for ${resetCandidate.candidate_name}. They can now start a new assessment.`);
      setResetCandidate(null);
      fetchSubmissions();
    } catch (err) {      setMessage(`Error: ${err.message}`);
      setResetCandidate(null);
    } finally {
      setResetLoading(false);
    }
  };

  // Open the remark modal for a submission
  const openRemarkModal = (sub) => {
    setRemarkTarget(sub);
    setRemarkText(sub.admin_remark || '');
    setRemarkError('');
  };

  const closeRemarkModal = () => {
    setRemarkTarget(null);
    setRemarkText('');
    setRemarkError('');
  };

  // Save (or clear via empty payload) the remark, then refresh button state
  const handleSaveRemark = async () => {
    if (!remarkTarget || remarkSaving) return;
    setRemarkSaving(true);
    setRemarkError('');
    try {
      const resp = await fetch(`${apiUrl}/admin/assessments/${remarkTarget.attempt_id}/remark`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ admin_remark: remarkText }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to save remark');
      setRemarkTarget(null);
      setRemarkText('');
      setMessage('Remark saved.');
      fetchSubmissions(); // refresh admin_remark / button state
    } catch (err) {
      // Keep remarkText so the admin does not lose their edit
      setRemarkError(err.message);
    } finally {
      setRemarkSaving(false);
    }
  };

  // Clear (delete) the remark for the open modal
  const handleClearRemark = async () => {
    if (!remarkTarget || remarkSaving) return;
    setRemarkSaving(true);
    setRemarkError('');
    try {
      const resp = await fetch(`${apiUrl}/admin/assessments/${remarkTarget.attempt_id}/remark`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to clear remark');
      setRemarkTarget(null);
      setRemarkText('');
      setMessage('Remark cleared.');
      fetchSubmissions();
    } catch (err) {
      setRemarkError(err.message);
    } finally {
      setRemarkSaving(false);
    }
  };

  // Delete individual assessment handler
  const handleDeleteAssessment = async () => {
    if (!deleteCandidate || deleteLoading) return;
    setDeleteLoading(true);
    try {
      const resp = await fetch(`${apiUrl}/admin/assessments/${deleteCandidate.attempt_id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Delete failed');
      }
      setMessage(`Assessment attempt deleted for ${deleteCandidate.candidate_name}.`);
      setDeleteCandidate(null);
      fetchSubmissions();
    } catch (err) {
      setMessage(`Error: ${err.message}`);
      setDeleteCandidate(null);
    } finally {
      setDeleteLoading(false);
    }
  };

  // Reset All assessments handler
  const handleResetAll = async () => {
    if (resetAllLoading) return;
    setResetAllLoading(true);
    try {
      const resp = await fetch(`${apiUrl}/admin/assessments/reset-all`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Reset All failed');
      }
      setMessage(data.message || `Reset ${data.reset_count} assessments.`);
      setShowResetAll(false);
      fetchSubmissions();
    } catch (err) {
      setMessage(`Error: ${err.message}`);
      setShowResetAll(false);
    } finally {
      setResetAllLoading(false);
    }
  };

  // Delete All assessments handler
  const handleDeleteAll = async () => {
    if (deleteAllLoading || deleteAllConfirmText !== 'DELETE ALL') return;
    setDeleteAllLoading(true);
    try {
      const resp = await fetch(`${apiUrl}/admin/assessments/all`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || 'Delete All failed');
      }
      setMessage(data.message || `Deleted ${data.deleted_count} assessments.`);
      setShowDeleteAll(false);
      setDeleteAllConfirmText('');
      fetchSubmissions();
    } catch (err) {
      setMessage(`Error: ${err.message}`);
      setShowDeleteAll(false);
      setDeleteAllConfirmText('');
    } finally {
      setDeleteAllLoading(false);
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
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold text-theme-primary">Admin Panel</h1>
          <div className="flex gap-2">
            <button
              onClick={() => navigate('/admin/descriptive')}
              className="px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white rounded-lg text-sm font-semibold transition-colors"
            >
              📝 Descriptive
            </button>
            <button
              onClick={() => navigate('/admin/coding')}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm font-semibold transition-colors"
            >
              💻 Coding Problems
            </button>
          </div>
        </div>

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

            {/* Assessment Configuration */}
            <div className="mt-8">
              <h2 className="text-xl font-bold text-theme-primary mb-4">Assessment Configuration</h2>
              {configs.map((cfg) => (
                <div key={cfg.id} className="bg-theme-secondary rounded-lg p-4 mb-3">
                  {editingConfig?.id === cfg.id ? (
                    <form onSubmit={handleConfigSubmit} className="space-y-3">
                      <input
                        placeholder="Name"
                        value={configForm.name ?? ''}
                        onChange={(e) => setConfigForm({ ...configForm, name: e.target.value })}
                        className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                      />
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="text-xs text-theme-muted mb-1 block">MCQ Questions</label>
                          <input
                            type="number"
                            min="1"
                            value={configForm.total_questions ?? ''}
                            onChange={(e) => {
                              const val = e.target.value === '' ? '' : parseInt(e.target.value, 10);
                              setConfigForm({ ...configForm, total_questions: val });
                            }}
                            className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                            required
                          />
                        </div>
                        <div>
                          <label className="text-xs text-theme-muted mb-1 block">Coding Problems</label>
                          <input
                            type="number"
                            min="0"
                            value={configForm.coding_problem_count ?? ''}
                            onChange={(e) => {
                              const val = e.target.value === '' ? '' : parseInt(e.target.value, 10);
                              setConfigForm({ ...configForm, coding_problem_count: val });
                            }}
                            className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                            required
                          />
                        </div>
                        <div>
                          <label className="text-xs text-theme-muted mb-1 block">Duration (minutes)</label>
                          <input
                            type="number"
                            min="1"
                            value={configForm.duration_minutes ?? ''}
                            onChange={(e) => {
                              const val = e.target.value === '' ? '' : parseInt(e.target.value, 10);
                              setConfigForm({ ...configForm, duration_minutes: val });
                            }}
                            className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                            required
                          />
                        </div>
                        <div>
                          <label className="text-xs text-theme-muted mb-1 block">Descriptive Questions</label>
                          <input
                            type="number"
                            min="0"
                            value={configForm.descriptive_question_count ?? ''}
                            onChange={(e) => {
                              const val = e.target.value === '' ? '' : parseInt(e.target.value, 10);
                              setConfigForm({ ...configForm, descriptive_question_count: val });
                            }}
                            className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                            required
                          />
                        </div>
                        <div>
                          <label className="text-xs text-theme-muted mb-1 block">Max Domains (1 or 2)</label>
                          <input
                            type="number"
                            min="1"
                            max="2"
                            value={configForm.max_domains ?? ''}
                            onChange={(e) => {
                              const val = e.target.value === '' ? '' : parseInt(e.target.value, 10);
                              setConfigForm({ ...configForm, max_domains: val });
                            }}
                            className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                            required
                          />
                        </div>
                      </div>
                      {configError && (
                        <p className="text-xs text-red-400 bg-red-900/20 border border-red-500/50 rounded px-3 py-2">
                          {configError}
                        </p>
                      )}
                      <div className="flex gap-2">
                        <button type="submit" className="flex-1 px-3 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm">Save</button>
                        <button type="button" onClick={() => { setEditingConfig(null); setConfigForm({}); setConfigError(''); }} className="px-3 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded text-sm">Cancel</button>
                      </div>
                    </form>
                  ) : (
                    <>
                      <div className="flex justify-between items-start">
                        <div>
                          <h3 className="font-semibold text-theme-primary">{cfg.name}</h3>
                          <span className={`text-xs px-2 py-0.5 rounded ${cfg.is_active ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
                            {cfg.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                        <button
                          onClick={() => { setEditingConfig(cfg); setConfigForm({ name: cfg.name, total_questions: cfg.total_questions, coding_problem_count: cfg.coding_problem_count ?? 0, descriptive_question_count: cfg.descriptive_question_count ?? 0, duration_minutes: cfg.duration_minutes, max_domains: cfg.max_domains, is_active: cfg.is_active }); setConfigError(''); }}
                          className="text-xs px-2 py-1 bg-blue-600 text-white rounded"
                        >
                          Edit
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-2 mt-3 text-xs text-theme-muted">
                        <span>MCQ Questions: {cfg.total_questions}</span>
                        <span>Coding Problems: {cfg.coding_problem_count ?? 0}</span>
                        <span>Descriptive: {cfg.descriptive_question_count ?? 0}</span>
                        <span>Duration: {cfg.duration_minutes}m</span>
                        <span>Max Domains: {cfg.max_domains}</span>
                      </div>
                      <p className="text-xs text-theme-muted mt-1">
                        2 domains → 50/50 split (total must be even)
                      </p>
                    </>
                  )}
                </div>
              ))}
              {configs.length === 0 && (
                <p className="text-theme-muted text-sm">No assessment configurations found.</p>
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

        {/* Assessment Responses / Leaderboard */}
        <div className="mt-12">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-bold text-theme-primary">Assessment Responses</h2>
            {submissions.length > 0 && (
              <div className="flex gap-2">
                <button
                  onClick={() => setShowResetAll(true)}
                  className="text-sm px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white rounded-lg font-semibold"
                >
                  Reset All
                </button>
                <button
                  onClick={() => setShowDeleteAll(true)}
                  className="text-sm px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-semibold"
                >
                  Delete All
                </button>
              </div>
            )}
          </div>

          {/* Filters */}
          <div className="bg-theme-secondary rounded-lg p-4 mb-4">
            <div className="flex flex-wrap gap-3 items-end">
              {/* Search */}
              <div className="flex-1 min-w-[200px]">
                <label className="text-xs text-theme-muted block mb-1">Search</label>
                <input
                  type="text"
                  placeholder="Name, email, or USN..."
                  value={subSearch}
                  onChange={(e) => setSubSearch(e.target.value)}
                  className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                />
              </div>

              {/* Semester filter */}
              <div>
                <label className="text-xs text-theme-muted block mb-1">Semester</label>
                <select
                  value={subSemester || ''}
                  onChange={(e) => setSubSemester(e.target.value ? parseInt(e.target.value) : null)}
                  className="px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                >
                  <option value="">All</option>
                  {SEMESTERS.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>

              {/* Branch filter */}
              <div>
                <label className="text-xs text-theme-muted block mb-1">Branch</label>
                <input
                  type="text"
                  placeholder="Branch..."
                  value={subBranch}
                  onChange={(e) => setSubBranch(e.target.value)}
                  className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                />
              </div>

              {/* Sort */}
              <div>
                <label className="text-xs text-theme-muted block mb-1">Sort by</label>
                <select
                  value={`${subSort}-${subOrder}`}
                  onChange={(e) => {
                    const [s, o] = e.target.value.split('-');
                    setSubSort(s);
                    setSubOrder(o);
                  }}
                  className="px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                >
                  <option value="score-desc">Score: Highest First</option>
                  <option value="score-asc">Score: Lowest First</option>
                  <option value="percentage-desc">Percentage: Highest First</option>
                  <option value="percentage-asc">Percentage: Lowest First</option>
                  <option value="submitted_at-desc">Submitted: Newest First</option>
                  <option value="submitted_at-asc">Submitted: Oldest First</option>
                  <option value="name-asc">Name: A → Z</option>
                  <option value="name-desc">Name: Z → A</option>
                </select>
              </div>

              {/* Clear filters */}
              <button
                onClick={() => {
                  setSubSearch('');
                  setSubSemester(null);
                  setSubBranch('');
                  setSubSort('score');
                  setSubOrder('desc');
                }}
                className="px-3 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded text-sm"
              >
                Clear Filters
              </button>
            </div>
          </div>

          {/* Submissions table */}
          {submissionsLoading ? (
            <div className="text-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-blue-500 mx-auto" />
              <p className="text-theme-muted mt-4">Loading submissions...</p>
            </div>
          ) : submissions.length === 0 ? (
            <div className="text-center py-12 bg-theme-secondary rounded-lg">
              <p className="text-theme-muted text-lg">No submitted assessments found.</p>
              <p className="text-theme-muted text-sm mt-2">Submissions will appear here once candidates complete their assessments.</p>
            </div>
          ) : (
            <div className="bg-theme-secondary rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-theme-tertiary">
                      <th className="px-4 py-3 text-left text-theme-muted font-medium">Rank</th>
                      <th className="px-4 py-3 text-left text-theme-muted font-medium">Candidate</th>
                      <th className="px-4 py-3 text-left text-theme-muted font-medium">USN</th>
                      <th className="px-4 py-3 text-left text-theme-muted font-medium">Domain</th>
                      <th className="px-4 py-3 text-left text-theme-muted font-medium">Score</th>
                      <th className="px-4 py-3 text-left text-theme-muted font-medium">%</th>
                      <th className="px-4 py-3 text-left text-theme-muted font-medium">Submitted</th>
                      <th className="px-4 py-3 text-right text-theme-muted font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {submissions.map((sub, idx) => (
                      <tr key={sub.attempt_id} className="border-t border-theme-secondary hover:bg-theme-tertiary/50">
                        <td className="px-4 py-3 text-theme-primary font-bold">
                          {idx + 1}
                        </td>
                        <td className="px-4 py-3">
                          <div className="text-theme-primary font-medium">{sub.candidate_name}</div>
                          <div className="text-theme-muted text-xs">{sub.email}</div>
                        </td>
                        <td className="px-4 py-3 text-theme-primary font-mono text-xs">{sub.usn}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {(sub.domain_names || []).map((d) => (
                              <span key={d} className="text-xs bg-blue-900/50 text-blue-300 px-2 py-0.5 rounded">
                                {d}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="font-bold text-theme-primary">
                            {sub.score}/{sub.max_score}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`font-bold ${
                            sub.percentage >= 80 ? 'text-green-400' :
                            sub.percentage >= 50 ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {sub.percentage}%
                          </span>
                        </td>
                        <td className="px-4 py-3 text-theme-muted text-xs">
                          {sub.submitted_at ? new Date(sub.submitted_at).toLocaleString('en-US', {
                            month: 'short', day: 'numeric',
                            hour: '2-digit', minute: '2-digit',
                          }) : '—'}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex gap-1 justify-end">
                            <button
                              onClick={() => navigate(`/admin/assessments/${sub.attempt_id}/results`)}
                              className="text-xs px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded"
                            >
                              View Responses
                            </button>
                            {/* Chat-shaped remark button — faded when no remark exists */}
                            <button
                              onClick={() => openRemarkModal(sub)}
                              title={sub.admin_remark ? 'View / edit remark' : 'Add remark'}
                              aria-label={
                                sub.admin_remark
                                  ? `Edit remark for ${sub.candidate_name}`
                                  : `Add remark for ${sub.candidate_name}`
                              }
                              className={`p-1.5 rounded ${
                                sub.admin_remark
                                  ? 'bg-blue-600 hover:bg-blue-700 text-white'
                                  : 'bg-gray-600/40 text-gray-400 cursor-pointer opacity-60 hover:opacity-100'
                              }`}
                            >
                              <svg
                                xmlns="http://www.w3.org/2000/svg"
                                viewBox="0 0 24 24"
                                fill="currentColor"
                                className="w-4 h-4"
                                aria-hidden="true"
                              >
                                <path
                                  fillRule="evenodd"
                                  d="M4.848 2.771A49.144 49.144 0 0 1 12 2.25c2.43 0 4.817.178 7.152.52 1.978.292 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.678-3.348 3.97-.759.1-1.507.18-2.274.226v1.535a2.25 2.25 0 0 1-3.527 1.855l-2.77-1.932a48.09 48.09 0 0 1-3.62-2.745c-.6-.503-.938-1.243-.938-2.015V6.74c0-1.946 1.37-3.678 3.348-3.97Z"
                                  clipRule="evenodd"
                                />
                              </svg>
                            </button>
                            {(sub.status === 'scored' || sub.status === 'submitted') && (
                              <>
                                <button
                                  onClick={() => setResetCandidate(sub)}
                                  className="text-xs px-3 py-1 bg-orange-600 hover:bg-orange-700 text-white rounded"
                                >
                                  Reset
                                </button>
                                <button
                                  onClick={() => setDeleteCandidate(sub)}
                                  className="text-xs px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded"
                                >
                                  Delete
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3 text-xs text-theme-muted border-t border-theme-secondary">
                Showing {submissions.length} submission{submissions.length !== 1 ? 's' : ''}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Reset Confirmation Modal */}
      {resetCandidate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-theme-secondary rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 className="text-xl font-bold text-theme-primary mb-4">Reset Assessment</h3>
            <p className="text-theme-muted mb-2">
              Are you sure you want to reset the assessment for{' '}
              <span className="font-semibold text-theme-primary">{resetCandidate.candidate_name}</span>?
            </p>
            <div className="bg-orange-900/20 border border-orange-500/50 rounded p-3 mb-4">
              <p className="text-orange-300 text-sm font-medium">⚠️ This will allow the candidate to take a new assessment.</p>
              <p className="text-orange-200 text-sm mt-1">Their previous assessment results will NOT be deleted.</p>
            </div>
            <p className="text-theme-muted text-sm mb-4">
              Previous score: {resetCandidate.score}/{resetCandidate.max_score} ({resetCandidate.percentage}%) — will be preserved in history.
            </p>
            <div className="flex gap-3">
              <button
                onClick={handleResetAssessment}
                disabled={resetLoading}
                className="flex-1 px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white rounded-lg font-semibold disabled:opacity-50"
              >
                {resetLoading ? 'Resetting...' : 'Confirm Reset'}
              </button>
              <button
                onClick={() => setResetCandidate(null)}
                disabled={resetLoading}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Remark Modal — admin-only private note on a submission */}
      {remarkTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-theme-secondary rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 className="text-xl font-bold text-theme-primary mb-1">Assessment Remark</h3>
            <p className="text-theme-muted text-sm mb-4">
              Private note for <span className="font-semibold text-theme-primary">{remarkTarget.candidate_name}</span> — visible to admins only.
            </p>
            <textarea
              value={remarkText}
              onChange={(e) => setRemarkText(e.target.value)}
              rows={5}
              maxLength={10000}
              placeholder="Write a remark about this submission..."
              className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm resize-y"
            />
            {remarkError && (
              <p className="text-xs text-red-400 bg-red-900/20 border border-red-500/50 rounded px-3 py-2 mt-2">
                {remarkError}
              </p>
            )}
            <div className="flex justify-between gap-3 mt-4">
              <button
                onClick={handleClearRemark}
                disabled={remarkSaving || !(remarkTarget.admin_remark || remarkText)}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-semibold disabled:opacity-40"
              >
                Clear
              </button>
              <div className="flex gap-3">
                <button
                  onClick={closeRemarkModal}
                  disabled={remarkSaving}
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveRemark}
                  disabled={remarkSaving}
                  className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg font-semibold disabled:opacity-50"
                >
                  {remarkSaving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteCandidate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-theme-secondary rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 className="text-xl font-bold text-theme-primary mb-4">Delete Assessment</h3>
            <p className="text-theme-muted mb-2">
              Are you sure you want to delete the assessment for{' '}
              <span className="font-semibold text-theme-primary">{deleteCandidate.candidate_name}</span>?
            </p>
            <div className="bg-red-900/20 border border-red-500/50 rounded p-3 mb-4">
              <p className="text-red-300 text-sm font-medium">⚠️ This permanently deletes this candidate's assessment attempt, including its answers, coding submissions, drafts, scores, and results.</p>
              <p className="text-red-200 text-sm mt-1">This cannot be undone.</p>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleDeleteAssessment}
                disabled={deleteLoading}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-semibold disabled:opacity-50"
              >
                {deleteLoading ? 'Deleting...' : 'Confirm Delete'}
              </button>
              <button
                onClick={() => setDeleteCandidate(null)}
                disabled={deleteLoading}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reset All Confirmation Modal */}
      {showResetAll && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-theme-secondary rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 className="text-xl font-bold text-theme-primary mb-4">Reset All Assessments</h3>
            <p className="text-theme-muted mb-2">
              Are you sure you want to reset ALL assessment attempts?
            </p>
            <div className="bg-orange-900/20 border border-orange-500/50 rounded p-3 mb-4">
              <p className="text-orange-300 text-sm font-medium">This will mark all candidate assessment attempts as reset.</p>
              <p className="text-orange-200 text-sm mt-1">Historical attempts and their data will be preserved. Candidates will be able to start a new assessment.</p>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleResetAll}
                disabled={resetAllLoading}
                className="flex-1 px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white rounded-lg font-semibold disabled:opacity-50"
              >
                {resetAllLoading ? 'Resetting...' : 'Confirm Reset All'}
              </button>
              <button
                onClick={() => setShowResetAll(false)}
                disabled={resetAllLoading}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete All Confirmation Modal */}
      {showDeleteAll && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-theme-secondary rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 className="text-xl font-bold text-theme-primary mb-4">Delete All Assessments</h3>
            <p className="text-theme-muted mb-2">
              This permanently deletes ALL candidate assessment attempts and their associated answers, coding submissions, drafts, scores, and results.
            </p>
            <div className="bg-red-900/20 border border-red-500/50 rounded p-3 mb-4">
              <p className="text-red-300 text-sm font-medium">⚠️ This cannot be undone.</p>
              <p className="text-red-200 text-sm mt-1">Domains, MCQs, coding problems, test cases, and candidate profiles will NOT be affected.</p>
            </div>
            <div className="mb-4">
              <label className="text-sm text-theme-muted block mb-1">Type <span className="font-bold text-theme-primary">DELETE ALL</span> to confirm:</label>
              <input
                type="text"
                value={deleteAllConfirmText}
                onChange={(e) => setDeleteAllConfirmText(e.target.value)}
                className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                placeholder="DELETE ALL"
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleDeleteAll}
                disabled={deleteAllLoading || deleteAllConfirmText !== 'DELETE ALL'}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-semibold disabled:opacity-50"
              >
                {deleteAllLoading ? 'Deleting...' : 'Delete All'}
              </button>
              <button
                onClick={() => { setShowDeleteAll(false); setDeleteAllConfirmText(''); }}
                disabled={deleteAllLoading}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminPanel;
