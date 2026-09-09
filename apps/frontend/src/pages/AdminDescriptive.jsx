import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * Admin Descriptive Questions Page
 *
 * Admin management for descriptive (free-text) questions.
 * Features:
 * - Create/edit/delete descriptive questions
 * - Image upload via Supabase Storage (no URL input)
 * - Word limit configuration
 * - Multi-domain assignment
 */

const AdminDescriptive = () => {
  const { getAuthHeaders } = useAuth();
  const navigate = useNavigate();

  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  // Questions state
  const [questions, setQuestions] = useState([]);
  const [selectedQuestion, setSelectedQuestion] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editingQuestion, setEditingQuestion] = useState(null);
  const [form, setForm] = useState({
    question_text: '',
    image_url: '',
    word_limit: '',
    domain_ids: [],
    is_active: true,
  });

  // Image upload state
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState('');
  const [uploading, setUploading] = useState(false);

  // Domains
  const [domains, setDomains] = useState([]);

  const [message, setMessage] = useState('');
  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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

  // Fetch domains
  const fetchDomains = useCallback(async () => {
    try {
      const resp = await fetch(`${apiUrl}/admin/domains`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setDomains(data);
      }
    } catch { /* silent */ }
  }, [apiUrl]);

  // Fetch questions
  const fetchQuestions = useCallback(async () => {
    try {
      const resp = await fetch(`${apiUrl}/admin/descriptive-questions`, { credentials: 'include' });
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

  // Image handling
  const handleImageChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
  };

  const uploadImage = async () => {
    if (!imageFile) return null;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', imageFile);
      const authHeaders = getAuthHeaders();
      // Do NOT forward Content-Type — let the browser set
      // multipart/form-data; boundary=... automatically.
      delete authHeaders['Content-Type'];
      const resp = await fetch(`${apiUrl}/admin/descriptive-questions/upload-image`, {
        method: 'POST',
        headers: authHeaders,
        credentials: 'include',
        body: formData,
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const detail = Array.isArray(err.detail)
          ? err.detail.map((e) => e.msg || e).join('; ')
          : err.detail || 'Failed to upload image';
        throw new Error(detail);
      }
      const data = await resp.json();
      return data.image_url;
    } finally {
      setUploading(false);
    }
  };

  const removeImage = () => {
    setImageFile(null);
    setImagePreview('');
    setForm((prev) => ({ ...prev, image_url: '' }));
  };

  // Submit handler
  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      // Upload image if a new file was selected
      let imageUrl = form.image_url;
      if (imageFile) {
        imageUrl = await uploadImage();
        if (!imageUrl) return; // upload failed
      }

      const payload = {
        question_text: form.question_text,
        image_url: imageUrl || null,
        word_limit: form.word_limit ? parseInt(form.word_limit, 10) : null,
        domain_ids: form.domain_ids,
        is_active: form.is_active,
      };

      const isEditing = !!editingQuestion;
      const url = isEditing
        ? `${apiUrl}/admin/descriptive-questions/${editingQuestion.id}`
        : `${apiUrl}/admin/descriptive-questions`;

      const resp = await fetch(url, {
        method: isEditing ? 'PUT' : 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      });

      if (resp.ok) {
        setMessage(isEditing ? 'Question updated successfully.' : 'Question created successfully.');
        setShowForm(false);
        setEditingQuestion(null);
        setForm({ question_text: '', image_url: '', word_limit: '', domain_ids: [], is_active: true });
        setImageFile(null);
        setImagePreview('');
        fetchQuestions();
      } else {
        const err = await resp.json();
        setMessage(`Error: ${err.detail || 'Failed to save question'}`);
      }
    } catch (err) {
      setMessage(`Error: ${err.message}`);
    }
  };

  // Delete handler
  const handleDelete = async (questionId) => {
    if (!window.confirm('Are you sure you want to delete this question?')) return;
    try {
      const resp = await fetch(`${apiUrl}/admin/descriptive-questions/${questionId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
      });
      if (resp.ok) {
        setMessage('Question deleted successfully.');
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

  // Edit handler
  const handleEdit = (q) => {
    setEditingQuestion(q);
    setForm({
      question_text: q.question_text,
      image_url: q.image_url || '',
      word_limit: q.word_limit || '',
      domain_ids: q.domain_ids || [],
      is_active: q.is_active,
    });
    setImagePreview(q.image_url || '');
    setImageFile(null);
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
            <h1 className="text-3xl font-bold text-theme-primary">Descriptive Questions</h1>
          </div>
          <button
            onClick={() => {
              setEditingQuestion(null);
              setForm({ question_text: '', image_url: '', word_limit: '', domain_ids: [], is_active: true });
              setImageFile(null);
              setImagePreview('');
              setShowForm(true);
            }}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold"
          >
            + Add Question
          </button>
        </div>

        {message && (
          <div className={`mb-4 p-3 rounded-lg text-sm ${message.startsWith('Error') ? 'bg-red-900/30 border border-red-500 text-red-300' : 'bg-green-900/30 border border-green-500 text-green-300'}`}>
            {message}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Questions List */}
          <div className="lg:col-span-1">
            <h2 className="text-xl font-bold text-theme-primary mb-4">Questions ({questions.length})</h2>
            <div className="space-y-2">
              {questions.map((q) => (
                <div
                  key={q.id}
                  onClick={() => setSelectedQuestion(q)}
                  className={`bg-theme-secondary rounded-lg p-3 cursor-pointer transition-all ${selectedQuestion?.id === q.id ? 'ring-2 ring-blue-500' : 'hover:bg-theme-tertiary'}`}
                >
                  <div className="flex justify-between items-start">
                    <p className="text-sm text-theme-primary line-clamp-2 flex-1">{q.question_text}</p>
                    <span className={`text-xs px-2 py-0.5 rounded ml-2 flex-shrink-0 ${q.is_active ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
                      {q.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {(q.domain_names || []).map((name, i) => (
                      <span key={i} className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">{name}</span>
                    ))}
                  </div>
                  {q.word_limit && (
                    <p className="text-xs text-theme-muted mt-1">Word limit: {q.word_limit}</p>
                  )}
                </div>
              ))}
              {questions.length === 0 && (
                <p className="text-theme-muted text-center py-8">No descriptive questions yet.</p>
              )}
            </div>
          </div>

          {/* Detail / Form Panel */}
          <div className="lg:col-span-2">
            {showForm ? (
              <form onSubmit={handleSubmit} className="bg-theme-secondary rounded-lg p-6 space-y-4">
                <h2 className="text-xl font-bold text-theme-primary mb-2">
                  {editingQuestion ? 'Edit Question' : 'Create Question'}
                </h2>

                <div>
                  <label className="block text-sm font-medium text-theme-primary mb-1">Question Text *</label>
                  <textarea
                    value={form.question_text}
                    onChange={(e) => setForm({ ...form, question_text: e.target.value })}
                    required
                    rows={5}
                    className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    placeholder="Enter the question text..."
                  />
                </div>

                {/* Image Upload */}
                <div>
                  <label className="block text-sm font-medium text-theme-primary mb-1">Image (optional)</label>
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    onChange={handleImageChange}
                    className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm file:mr-4 file:py-1 file:px-3 file:rounded file:border-0 file:text-sm file:bg-blue-600 file:text-white file:cursor-pointer"
                  />
                  {imagePreview && (
                    <div className="mt-2 relative inline-block">
                      <img src={imagePreview} alt="Preview" className="max-h-40 rounded border border-theme-secondary" />
                      <button
                        type="button"
                        onClick={removeImage}
                        className="absolute top-1 right-1 bg-red-600 text-white rounded-full w-6 h-6 flex items-center justify-center text-xs"
                      >
                        ×
                      </button>
                    </div>
                  )}
                </div>

                {/* Word Limit */}
                <div>
                  <label className="block text-sm font-medium text-theme-primary mb-1">Word Limit (optional)</label>
                  <input
                    type="number"
                    min="1"
                    value={form.word_limit}
                    onChange={(e) => setForm({ ...form, word_limit: e.target.value })}
                    className="w-full px-3 py-2 bg-theme-input border border-theme-secondary rounded text-theme-primary text-sm"
                    placeholder="Leave empty for no limit"
                  />
                </div>

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
                  <button type="submit" disabled={uploading} className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded text-sm font-semibold disabled:opacity-50">
                    {uploading ? 'Uploading...' : editingQuestion ? 'Update' : 'Create'}
                  </button>
                  <button type="button" onClick={() => { setShowForm(false); setEditingQuestion(null); }} className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded text-sm">
                    Cancel
                  </button>
                </div>
              </form>
            ) : selectedQuestion ? (
              <div className="bg-theme-secondary rounded-lg p-6">
                <div className="flex justify-between items-start mb-4">
                  <h2 className="text-xl font-bold text-theme-primary">Question Detail</h2>
                  <div className="flex gap-2">
                    <button onClick={() => handleEdit(selectedQuestion)} className="text-xs px-3 py-1 bg-blue-600 text-white rounded">Edit</button>
                    <button onClick={() => handleDelete(selectedQuestion.id)} className="text-xs px-3 py-1 bg-red-600 text-white rounded">Delete</button>
                  </div>
                </div>
                <p className="text-theme-primary whitespace-pre-wrap mb-4">{selectedQuestion.question_text}</p>
                {selectedQuestion.image_url && (
                  <img src={selectedQuestion.image_url} alt="Question" className="max-h-60 rounded mb-4 border border-theme-secondary" />
                )}
                {selectedQuestion.word_limit && (
                  <p className="text-sm text-theme-muted mb-2">Word limit: {selectedQuestion.word_limit}</p>
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
                Select a question from the list or create a new one.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminDescriptive;
