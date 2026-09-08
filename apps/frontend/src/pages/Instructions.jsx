import { useNavigate } from 'react-router-dom';

/**
 * Instructions Page
 *
 * Static placeholder with two sections: Coding and MCQs.
 * "Next" navigates to the existing Domains page.
 */
const Instructions = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-theme-primary py-12 px-4">
      <div className="max-w-3xl mx-auto">
        <h1 className="text-3xl font-bold text-theme-primary mb-8 text-center">
          Assessment Instructions
        </h1>

        {/* Coding Section */}
        <div className="bg-theme-secondary rounded-lg p-6 mb-6">
          <h2 className="text-xl font-bold text-theme-primary mb-4 flex items-center gap-2">
            <span className="text-2xl">💻</span> Coding
          </h2>
          <ul className="space-y-3 text-theme-secondary">
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                You will be presented with coding problems that you must solve
                using the integrated code editor.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                Supported languages include Python, C++, and Java. Select your
                preferred language from the dropdown.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                Use the <strong>Run</strong> button to test your solution against
                sample test cases before submitting.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                Your code is evaluated against hidden test cases on submission.
                Make sure your solution handles all edge cases.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                Each problem has a time limit. Ensure your solution is efficient.
              </span>
            </li>
          </ul>
        </div>

        {/* MCQs Section */}
        <div className="bg-theme-secondary rounded-lg p-6 mb-8">
          <h2 className="text-xl font-bold text-theme-primary mb-4 flex items-center gap-2">
            <span className="text-2xl">📝</span> MCQs
          </h2>
          <ul className="space-y-3 text-theme-secondary">
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                Multiple-choice questions test your theoretical knowledge in the
                selected domain(s).
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                Each question has four options (A, B, C, D). Select the best
                answer for each.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                Your answers are saved automatically as you select them.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                You can navigate between questions using the question navigator.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-blue-400 mt-1">•</span>
              <span>
                Review all answers before submitting. Once submitted, you cannot
                change your answers.
              </span>
            </li>
          </ul>
        </div>

        {/* Next Button */}
        <div className="flex justify-center">
          <button
            onClick={() => navigate('/domains')}
            className="px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-semibold text-lg transition-colors"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
};

export default Instructions;
