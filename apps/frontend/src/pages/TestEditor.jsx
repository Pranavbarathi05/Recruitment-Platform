import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { CodeEditor, Timer } from '../components';
import { useAuth } from '../hooks/useAuth';
import { getTestStatus } from '../utils/auth';

/**
 * TestEditor Page
 *
 * Test page for the CodeEditor component with Timer functionality.
 * Requires authentication (enforced by ProtectedRoute).
 */
function TestEditor() {
  const { domainId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [questions, setQuestions] = useState([]);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [code, setCode] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [testDuration, setTestDuration] = useState(20);
  const [domainName, setDomainName] = useState('');
  const [testExpired, setTestExpired] = useState(false);

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    if (domainId) {
      const status = getTestStatus(domainId, user?.id);
      if (status === 'expired') {
        setTestExpired(true);
        setLoading(false);
        return;
      }
    }

    const fetchTestData = async () => {
      if (!domainId) {
        setQuestions([{
          id: 'demo',
          title: 'Demo Question',
          description: 'This is a demo. Write any Python code you like!',
          base_code: '# Write your Python code here\n\ndef hello():\n    print("Hello, World!")\n\nhello()\n'
        }]);
        setCode('# Write your Python code here\n\ndef hello():\n    print("Hello, World!")\n\nhello()\n');
        setTestDuration(15);
        setDomainName('Demo');
        setLoading(false);
        return;
      }

      try {
        setLoading(true);

        const domainsResponse = await fetch(`${apiUrl}/questions/domains`);
        if (domainsResponse.ok) {
          const domains = await domainsResponse.json();
          const currentDomain = domains.find(d => d.id === domainId);
          if (currentDomain) {
            setTestDuration(currentDomain.durationMinutes);
            setDomainName(currentDomain.name);
          }
        }

        const questionsResponse = await fetch(`${apiUrl}/questions/${domainId}`);

        if (!questionsResponse.ok) {
          throw new Error(`HTTP error! status: ${questionsResponse.status}`);
        }

        const data = await questionsResponse.json();
        setQuestions(data);

        if (data.length > 0) {
          setCode(data[0].base_code || '// Start coding here...');
        }
      } catch (err) {
        console.error('Error fetching test data:', err);
        alert('Failed to load test. Please try again.');
      } finally {
        setLoading(false);
      }
    };

    fetchTestData();
  }, [domainId, navigate, apiUrl, user?.id]);

  const currentQuestion = questions[currentQuestionIndex];

  const handleCodeChange = (value) => {
    setCode(value);
  };

  const handleTimeUp = () => {
    console.log('Time is up! Auto-submitting code...');
    setTestExpired(true);
    submitCode(true);
  };

  const submitCode = (timeExpired = false) => {
    setIsSubmitting(true);
    console.log('Submitting code:', code);

    setTimeout(() => {
      if (timeExpired) {
        alert('⏰ Time has expired! Your code has been auto-submitted.\n\n' +
              `Question: ${currentQuestion?.title}\n\n` +
              'Your code:\n' + code +
              '\n\nYou can no longer access this test.');
        setIsSubmitting(false);
        setTestExpired(true);
      } else {
        alert('Code submitted successfully!\n\n' +
              `Question: ${currentQuestion?.title}\n\n` +
              'Your code:\n' + code);
        setIsSubmitting(false);

        if (currentQuestionIndex < questions.length - 1 && !testExpired) {
          const nextIndex = currentQuestionIndex + 1;
          setCurrentQuestionIndex(nextIndex);
          setCode(questions[nextIndex].base_code || '// Start coding here...');
        }
      }
    }, 1000);
  };

  if (testExpired) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="text-center bg-theme-secondary border border-red-500 rounded-lg p-8 max-w-md">
          <div className="text-red-500 text-6xl mb-4">⏰</div>
          <h2 className="text-2xl font-bold text-theme-primary mb-4">Test Expired</h2>
          <p className="text-theme-muted mb-6">
            Your time for this test has ended. You can no longer access or submit answers for this test.
          </p>
          <button
            onClick={() => navigate('/domains')}
            className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold"
          >
            Back to Domains
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-blue-500"></div>
      </div>
    );
  }

  if (!currentQuestion) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-theme-primary mb-4">No questions available</h2>
          <a href="/domains" className="text-blue-400 hover:underline">Go back to domains</a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-theme-primary p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-4xl font-bold text-theme-primary">{currentQuestion.title}</h1>
            <p className="text-theme-secondary mt-2">
              {domainName && <span className="font-semibold">{domainName} · </span>}
              Question {currentQuestionIndex + 1} of {questions.length}
            </p>
          </div>
          <Timer
            durationMinutes={testDuration}
            onTimeUp={handleTimeUp}
            testId={`test-${domainId || 'demo'}`}
            userId={user?.id}
          />
        </div>

        <div className="bg-theme-secondary border border-theme-primary rounded-lg p-6 mb-6">
          <h2 className="text-xl font-semibold text-theme-primary mb-2">Problem Statement</h2>
          <p className="text-theme-muted">{currentQuestion.description}</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-1 gap-8">
          <div className="bg-theme-secondary rounded-lg p-4 border border-theme-primary">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-theme-primary text-lg font-semibold">Code Editor</h2>
              <div className="flex gap-3">
                {currentQuestionIndex < questions.length - 1 && (
                  <button
                    onClick={() => {
                      const nextIndex = currentQuestionIndex + 1;
                      setCurrentQuestionIndex(nextIndex);
                      setCode(questions[nextIndex].base_code || '// Start coding here...');
                    }}
                    className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg font-semibold transition-colors"
                  >
                    Skip to Next
                  </button>
                )}
                <button
                  onClick={() => submitCode(false)}
                  disabled={isSubmitting || testExpired}
                  className="bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white px-6 py-2 rounded-lg font-semibold transition-colors"
                >
                  {isSubmitting ? 'Submitting...' : 'Submit Code'}
                </button>
              </div>
            </div>
            <CodeEditor
              language="python"
              theme="vs-dark"
              defaultValue={code}
              value={code}
              onChange={handleCodeChange}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default TestEditor;
