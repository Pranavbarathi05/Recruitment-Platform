import { useNavigate } from 'react-router-dom';

/**
 * Submission Confirmed Page
 *
 * Simple confirmation shown after a candidate submits an assessment.
 * Displays NO scoring data, correct answers, or performance information.
 */
const SubmissionConfirmed = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-theme-primary flex items-center justify-center py-12 px-4">
      <div className="bg-theme-secondary rounded-lg p-8 max-w-md w-full text-center">
        <div className="mb-6">
          <div className="w-16 h-16 bg-green-900/30 border-2 border-green-500 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-theme-primary mb-2">
            Assessment Submitted
          </h1>
          <p className="text-theme-muted">
            Your assessment has been successfully submitted.
          </p>
        </div>

        <div className="bg-theme-primary rounded-lg p-4 mb-6">
          <p className="text-theme-secondary text-sm">
            Your responses have been recorded.
          </p>
          <p className="text-theme-secondary text-sm mt-2">
            The results will be reviewed by the recruitment team.
          </p>
        </div>

        <button
          onClick={() => navigate('/domains')}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold transition-colors"
        >
          Back to Domains
        </button>
      </div>
    </div>
  );
};

export default SubmissionConfirmed;
