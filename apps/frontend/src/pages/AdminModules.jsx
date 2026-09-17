import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * Admin Assessment Modules Page
 *
 * Configures the per-domain, per-tier module counts consumed by the
 * assessment planner:
 *   - MCQ count
 *   - Descriptive count
 *   - Hands-on enabled / count / additional minutes
 *   - Notes
 *
 * Backend API (Phase 7A):
 *   GET /admin/assessment/modules
 *   GET /admin/assessment/modules/{domain_id}
 *   PUT /admin/assessment/modules/{domain_id}
 *
 * Coding problems are GLOBAL and deliberately absent here — coding is not a
 * per-domain module. Domain tier availability comes from the domain's
 * assessment_scope, not from a separate candidate field.
 */

// Which module configuration families a domain exposes. Mirrors the backend's
// SCOPE_ALLOWED_APPLIES_TO — the backend remains the final authority.
const FAMILIES_BY_SCOPE = {
  technical: ['junior', 'senior'],
  organizational: ['organizational'],
};

const FAMILY_LABELS = {
  junior: 'Junior',
  senior: 'Senior',
  organizational: 'Organizational',
};

const EMPTY_FORM = {
  mcq_count: 0,
  descriptive_count: 0,
  hands_on_enabled: false,
  hands_on_count: 0,
  hands_on_additional_minutes: 0,
  notes: '',
};

// Non-negative integer coercion for the numeric fields.
const toInt = (value) => {
  const n = parseInt(value, 10);
  if (Number.isNaN(n)) return 0;
  return Math.max(0, n);
};

const AdminModules = () => {
  const { getAuthHeaders } = useAuth();
  const navigate = useNavigate();

  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  const [modules, setModules] = useState([]);
  const [selectedDomainId, setSelectedDomainId] = useState(null);
  const [family, setFamily] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [preflight, setPreflight] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // Admin check — same probe as the other admin pages.
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

  const fetchModules = useCallback(async () => {
    try {
      const resp = await fetch(`${apiUrl}/admin/assessment/modules`, {
        credentials: 'include',
      });
      if (resp.ok) {
        const data = await resp.json();
        setModules(Array.isArray(data) ? data : []);
      }
    } catch { /* silent */ }
  }, [apiUrl]);

  useEffect(() => {
    if (isAdmin) {
      // Async fetch — setState happens after await, never synchronously.
      // Same pattern as AdminDescriptive.jsx / AdminHandsOn.jsx.
      fetchModules();
    }
  }, [isAdmin, fetchModules]);

  // Active domains only — inactive domains are not configurable surfaces.
  const activeModules = modules.filter((m) => m?.domain?.is_active);

  const selectedModule = activeModules.find(
    (m) => m.domain.id === selectedDomainId
  ) || null;

  const families = selectedModule
    ? FAMILIES_BY_SCOPE[selectedModule.domain.assessment_scope] || []
    : [];

  const existingConfig = selectedModule && family
    ? (selectedModule.configs || []).find((c) => c.applies_to === family) || null
    : null;

  const isConfigured = !!existingConfig;

  // Load a family's stored configuration into the form. An absent row yields
  // the explicit unconfigured state — nothing is auto-created.
  const loadForm = (entry, targetFamily) => {
    const cfg = (entry?.configs || []).find((c) => c.applies_to === targetFamily);
    if (cfg) {
      setForm({
        mcq_count: cfg.mcq_count ?? 0,
        descriptive_count: cfg.descriptive_count ?? 0,
        hands_on_enabled: !!cfg.hands_on_enabled,
        hands_on_count: cfg.hands_on_enabled ? cfg.hands_on_count ?? 0 : 0,
        hands_on_additional_minutes: cfg.hands_on_enabled
          ? cfg.hands_on_additional_minutes ?? 0
          : 0,
        notes: cfg.notes || '',
      });
    } else {
      setForm(EMPTY_FORM);
    }
    setPreflight(null);
  };

  const handleSelectDomain = (entry) => {
    setSelectedDomainId(entry.domain.id);
    const nextFamilies = FAMILIES_BY_SCOPE[entry.domain.assessment_scope] || [];
    const nextFamily = nextFamilies[0] || null;
    setFamily(nextFamily);
    loadForm(entry, nextFamily);
    setMessage('');
  };

  const handleSelectFamily = (nextFamily) => {
    setFamily(nextFamily);
    loadForm(selectedModule, nextFamily);
  };

  const handleHandsOnToggle = (checked) => {
    setForm((prev) => ({
      ...prev,
      hands_on_enabled: checked,
      // Disabled Hands-on carries no count and no time — reset both so a
      // stale value can never be submitted.
      hands_on_count: checked ? prev.hands_on_count : 0,
      hands_on_additional_minutes: checked ? prev.hands_on_additional_minutes : 0,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedModule || !family || saving) return;

    setSaving(true);
    try {
      const payload = {
        applies_to: family,
        mcq_count: toInt(form.mcq_count),
        descriptive_count: toInt(form.descriptive_count),
        hands_on_enabled: !!form.hands_on_enabled,
        hands_on_count: form.hands_on_enabled ? toInt(form.hands_on_count) : 0,
        hands_on_additional_minutes: form.hands_on_enabled
          ? toInt(form.hands_on_additional_minutes)
          : 0,
        notes: form.notes ? form.notes : null,
      };

      const resp = await fetch(
        `${apiUrl}/admin/assessment/modules/${selectedModule.domain.id}`,
        {
          method: 'PUT',
          headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(payload),
        }
      );

      if (resp.ok) {
        const data = await resp.json();
        setPreflight(data.preflight || null);
        setMessage('Configuration saved successfully.');
        // Reconcile the displayed state with what the server actually stored.
        fetchModules();
      } else {
        const err = await resp.json().catch(() => ({}));
        const detail = Array.isArray(err.detail)
          ? err.detail.map((d) => d.msg || d).join('; ')
          : err.detail || 'Failed to save configuration';
        setPreflight(null);
        setMessage(`Error: ${detail}`);
      }
    } catch (err) {
      setMessage(`Error: ${err.message}`);
    } finally {
      setSaving(false);
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

  const hardErrors = preflight?.hard_errors || [];
  const warnings = preflight?.warnings || [];
  const handsOnDisabled = !form.hands_on_enabled;
  const inputClass =
    'w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm disabled:opacity-50 disabled:cursor-not-allowed';

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
            <h1 className="text-3xl font-bold text-theme-primary">Assessment Modules</h1>
          </div>
        </div>

        {message && (
          <div className={`mb-4 p-3 rounded-lg text-sm ${message.startsWith('Error') ? 'bg-red-900/30 border border-red-500 text-red-300' : 'bg-green-900/30 border border-green-500 text-green-300'}`}>
            {message}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Domain list */}
          <div className="lg:col-span-1">
            <h2 className="text-xl font-bold text-theme-primary mb-4">
              Domains ({activeModules.length})
            </h2>
            <div className="space-y-2">
              {activeModules.map((entry) => {
                const configuredCount = (entry.configs || []).length;
                const expectedCount =
                  (FAMILIES_BY_SCOPE[entry.domain.assessment_scope] || []).length;
                const fullyConfigured =
                  expectedCount > 0 && configuredCount >= expectedCount;
                return (
                  <div
                    key={entry.domain.id}
                    onClick={() => handleSelectDomain(entry)}
                    className={`bg-theme-secondary rounded-lg p-3 cursor-pointer transition-all ${selectedDomainId === entry.domain.id ? 'ring-2 ring-blue-500' : 'hover:bg-theme-tertiary'}`}
                  >
                    <div className="flex justify-between items-start">
                      <p className="text-sm text-theme-primary font-medium flex-1">
                        {entry.domain.name}
                      </p>
                      <span className={`text-xs px-2 py-0.5 rounded ml-2 flex-shrink-0 ${fullyConfigured ? 'bg-green-900/50 text-green-300' : 'bg-yellow-900/50 text-yellow-300'}`}>
                        {fullyConfigured ? 'Configured' : 'Not configured'}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-2">
                      <span className="text-xs px-2 py-0.5 bg-purple-900/50 text-purple-300 rounded">
                        {entry.domain.assessment_scope}
                      </span>
                      <span className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">
                        {configuredCount}/{expectedCount} tiers
                      </span>
                    </div>
                  </div>
                );
              })}
              {activeModules.length === 0 && (
                <p className="text-theme-muted text-center py-8">
                  No active domains to configure.
                </p>
              )}
            </div>
          </div>

          {/* Editor */}
          <div className="lg:col-span-2">
            {selectedModule && family ? (
              <form onSubmit={handleSubmit} className="bg-theme-secondary rounded-lg p-6 space-y-4">
                <div className="flex items-start justify-between">
                  <div>
                    <h2 className="text-xl font-bold text-theme-primary">
                      {selectedModule.domain.name}
                    </h2>
                    <p className="text-xs text-theme-muted mt-1">
                      {selectedModule.domain.assessment_scope} domain
                    </p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded ${isConfigured ? 'bg-green-900/50 text-green-300' : 'bg-yellow-900/50 text-yellow-300'}`}>
                    {isConfigured ? 'Configured' : 'Not configured'}
                  </span>
                </div>

                {/* Tier / family tabs */}
                <div className="flex gap-2">
                  {families.map((f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => handleSelectFamily(f)}
                      className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${family === f ? 'bg-blue-600 text-white' : 'bg-theme-tertiary text-theme-muted hover:text-theme-primary'}`}
                    >
                      {FAMILY_LABELS[f] || f}
                    </button>
                  ))}
                </div>

                {!isConfigured && (
                  <p className="text-xs text-theme-muted">
                    No {FAMILY_LABELS[family] || family} configuration exists for this
                    domain yet. Fill in the counts and save to create it.
                  </p>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="mcq_count" className="block text-sm font-medium text-theme-primary mb-1">
                      MCQ count
                    </label>
                    <input
                      id="mcq_count"
                      type="number"
                      min="0"
                      value={form.mcq_count}
                      onChange={(e) => setForm({ ...form, mcq_count: toInt(e.target.value) })}
                      disabled={saving}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label htmlFor="descriptive_count" className="block text-sm font-medium text-theme-primary mb-1">
                      Descriptive count
                    </label>
                    <input
                      id="descriptive_count"
                      type="number"
                      min="0"
                      value={form.descriptive_count}
                      onChange={(e) => setForm({ ...form, descriptive_count: toInt(e.target.value) })}
                      disabled={saving}
                      className={inputClass}
                    />
                  </div>
                </div>

                {/* Hands-on */}
                <div className="border border-theme-secondary rounded-lg p-4 space-y-3">
                  <label className="flex items-center gap-2 text-sm text-theme-primary cursor-pointer">
                    <input
                      id="hands_on_enabled"
                      type="checkbox"
                      checked={form.hands_on_enabled}
                      onChange={(e) => handleHandsOnToggle(e.target.checked)}
                      disabled={saving}
                      className="rounded"
                    />
                    Hands-on enabled
                  </label>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label htmlFor="hands_on_count" className="block text-sm font-medium text-theme-primary mb-1">
                        Hands-on count
                      </label>
                      <input
                        id="hands_on_count"
                        type="number"
                        min="0"
                        value={form.hands_on_count}
                        onChange={(e) => setForm({ ...form, hands_on_count: toInt(e.target.value) })}
                        disabled={handsOnDisabled || saving}
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label htmlFor="hands_on_additional_minutes" className="block text-sm font-medium text-theme-primary mb-1">
                        Additional minutes
                      </label>
                      <input
                        id="hands_on_additional_minutes"
                        type="number"
                        min="0"
                        value={form.hands_on_additional_minutes}
                        onChange={(e) => setForm({ ...form, hands_on_additional_minutes: toInt(e.target.value) })}
                        disabled={handsOnDisabled || saving}
                        className={inputClass}
                      />
                    </div>
                  </div>

                  <p className="text-xs text-theme-muted">
                    Additional minutes apply only while Hands-on is enabled. When
                    Hands-on is disabled, its count and additional time are forced
                    to 0.
                  </p>
                </div>

                <div>
                  <label htmlFor="module_notes" className="block text-sm font-medium text-theme-primary mb-1">
                    Notes
                  </label>
                  <textarea
                    id="module_notes"
                    rows={2}
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    disabled={saving}
                    className={inputClass}
                    placeholder="Optional admin note about this configuration"
                  />
                </div>

                <div className="flex gap-2 pt-1">
                  <button
                    type="submit"
                    disabled={saving}
                    className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm font-semibold disabled:opacity-50"
                  >
                    {saving ? 'Saving...' : 'Save configuration'}
                  </button>
                </div>

                {/* Preflight — returned by the PUT response */}
                {preflight && (
                  <div className="bg-theme-tertiary rounded-lg p-4 space-y-2">
                    <h3 className="text-sm font-semibold text-theme-primary">Preflight</h3>
                    <div className="grid grid-cols-2 gap-1 text-sm">
                      <span className="text-theme-muted">Available MCQs:</span>
                      <span className="text-theme-primary">
                        {preflight.mcq_available}
                        {preflight.mcq_required_semester != null
                          ? ` (semester ${preflight.mcq_required_semester})`
                          : ''}
                      </span>
                      <span className="text-theme-muted">Available descriptive:</span>
                      <span className="text-theme-primary">{preflight.descriptive_available}</span>
                      <span className="text-theme-muted">Available hands-on:</span>
                      <span className="text-theme-primary">{preflight.hands_on_available}</span>
                    </div>

                    {hardErrors.length > 0 && (
                      <div className="bg-red-900/30 border border-red-500 text-red-300 rounded p-2 text-sm">
                        <p className="font-semibold">Blocking errors</p>
                        <ul className="list-disc list-inside">
                          {hardErrors.map((err, i) => (
                            <li key={i}>{err}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {warnings.length > 0 && (
                      <div className="bg-yellow-900/30 border border-yellow-500 text-yellow-300 rounded p-2 text-sm">
                        <p className="font-semibold">Advisory warnings</p>
                        <ul className="list-disc list-inside">
                          {warnings.map((w, i) => (
                            <li key={i}>{w}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </form>
            ) : (
              <div className="bg-theme-secondary rounded-lg p-12 text-center text-theme-muted">
                Select a domain to configure its assessment modules.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminModules;
