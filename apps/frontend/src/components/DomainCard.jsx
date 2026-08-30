import { useNavigate } from 'react-router-dom';
import PropTypes from 'prop-types';
import { useAuth } from '../hooks/useAuth';
import { getTestStatus } from '../utils/auth';

/**
 * DomainCard Component
 *
 * Displays a single domain card with:
 * - Domain name
 * - Question count
 * - Start Test button (with status checking)
 * - DSC themed colors
 */
const DomainCard = ({ domain }) => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const testStatus = getTestStatus(domain.id, user?.id);

  // DSC theme colors for different domains
  const domainColors = {
    machineLearning: 'from-blue-600 to-blue-800',
    webDevelopment: 'from-teal-600 to-teal-800',
    userInterface: 'from-purple-600 to-purple-800',
    cyberSecurity: 'from-red-600 to-red-800',
    backendDevelopment: 'from-green-600 to-green-800',
    testDomain: 'from-indigo-600 to-purple-700',
  };

  // Get the gradient color for this domain, default to blue
  const gradientColor = domainColors[domain.id] || 'from-blue-600 to-blue-800';

  const handleStartTest = () => {
    if (testStatus === 'expired') {
      alert('This test has expired. You can no longer take this test.');
      return;
    }

    // Navigate to the test editor with the domain
    navigate(`/test/${domain.id}`);
  };

  // Get button text and style based on status
  const getButtonConfig = () => {
    switch (testStatus) {
      case 'login_required':
        return {
          text: 'Login to Start',
          className: 'bg-blue-600 hover:bg-blue-700',
          disabled: false,
        };
      case 'in_progress':
        return {
          text: 'Continue Test',
          className: 'bg-yellow-600 hover:bg-yellow-700',
          disabled: false,
        };
      case 'expired':
        return {
          text: 'Test Expired',
          className: 'bg-gray-600 cursor-not-allowed',
          disabled: true,
        };
      default:
        return {
          text: 'Start Test',
          className: `bg-gradient-to-r ${gradientColor} hover:opacity-90`,
          disabled: false,
        };
    }
  };

  const buttonConfig = getButtonConfig();

  return (
    <div className="bg-theme-secondary rounded-lg overflow-hidden hover:transform hover:scale-105 transition-all duration-300 shadow-lg hover:shadow-2xl">
      {/* Colored header bar with gradient */}
      <div className={`h-2 bg-gradient-to-r ${gradientColor}`} />

      <div className="p-6">
        {/* Domain Name */}
        <h3 className="text-2xl font-bold text-theme-primary mb-3">
          {domain.name}
        </h3>

        {/* Question Count and Duration */}
        <div className="flex items-center gap-2 mb-4">
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-theme-tertiary text-theme-muted">
            {domain.questionCount} {domain.questionCount === 1 ? 'Question' : 'Questions'}
          </span>
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-900/50 text-blue-300">
            ⏱️ {domain.durationMinutes} min
          </span>
        </div>

        {/* Start Test Button */}
        <button
          onClick={handleStartTest}
          disabled={buttonConfig.disabled}
          className={`w-full ${buttonConfig.className} text-white font-semibold py-3 px-6 rounded-lg transition-opacity duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 ${
            buttonConfig.disabled ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {buttonConfig.text}
        </button>
      </div>
    </div>
  );
};

DomainCard.propTypes = {
  domain: PropTypes.shape({
    id: PropTypes.string.isRequired,
    name: PropTypes.string.isRequired,
    questionCount: PropTypes.number.isRequired,
    durationMinutes: PropTypes.number.isRequired,
  }).isRequired,
};

export default DomainCard;
