import { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';

/**
 * Timer Component
 *
 * Displays a countdown timer for timed assessments.
 * - Persists start time in localStorage to survive page refreshes
 * - Turns red when less than 5 minutes remain
 * - Auto-submits when timer reaches zero
 * - Uses userId prop for localStorage key namespacing
 */
const Timer = ({ durationMinutes, onTimeUp, testId, userId }) => {
  const storageKey = userId ? `timer_${testId}_${userId}` : `timer_${testId}`;

  const [isWarning, setIsWarning] = useState(false);
  const intervalRef = useRef(null);
  const hasSubmitted = useRef(false);

  // Calculate initial time remaining from localStorage
  const getInitialTimeRemaining = () => {
    const storedStartTime = localStorage.getItem(storageKey);
    if (!storedStartTime) return durationMinutes * 60;

    const startTime = parseInt(storedStartTime, 10);
    const elapsedSeconds = Math.floor((Date.now() - startTime) / 1000);
    return Math.max(0, durationMinutes * 60 - elapsedSeconds);
  };

  const [timeRemaining, setTimeRemaining] = useState(getInitialTimeRemaining);

  useEffect(() => {
    // Set start time if not already set
    const storedStartTime = localStorage.getItem(storageKey);
    if (!storedStartTime) {
      localStorage.setItem(storageKey, Date.now().toString());
    }

    // If already expired when loading, mark as expired and don't allow restart
    if (timeRemaining === 0) {
      if (!hasSubmitted.current) {
        hasSubmitted.current = true;
        // Mark test as expired in localStorage
        localStorage.setItem(`${storageKey}_expired`, 'true');
        onTimeUp();
      }
      return;
    }

    // Set up interval to update timer every second
    intervalRef.current = setInterval(() => {
      setTimeRemaining((prev) => {
        const newTime = prev - 1;

        // Check if we should show warning (less than 5 minutes)
        if (newTime <= 300 && newTime > 0) {
          setIsWarning(true);
        }

        // Time's up - trigger auto-submit and prevent restart
        if (newTime <= 0) {
          clearInterval(intervalRef.current);
          if (!hasSubmitted.current) {
            hasSubmitted.current = true;
            // Mark test as expired, don't remove the start time
            localStorage.setItem(`${storageKey}_expired`, 'true');
            onTimeUp();
          }
          return 0;
        }

        return newTime;
      });
    }, 1000);

    // Cleanup function
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [durationMinutes, onTimeUp, storageKey, testId, timeRemaining]);

  // Format time as MM:SS
  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="flex items-center space-x-3">
      <div
        className={`flex items-center space-x-2 px-4 py-2 rounded-lg font-mono text-lg font-bold transition-colors duration-300 ${
          isWarning
            ? 'bg-red-900/50 text-red-300 border-2 border-red-500 animate-pulse'
            : 'bg-blue-900/50 text-blue-300 border-2 border-blue-500'
        }`}
      >
        <svg
          className={`w-5 h-5 ${isWarning ? 'text-red-400' : 'text-blue-400'}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <span>{formatTime(timeRemaining)}</span>
      </div>

      {isWarning && timeRemaining > 0 && (
        <span className="text-red-400 text-sm font-semibold animate-pulse">
          ⚠️ Less than 5 minutes remaining!
        </span>
      )}

      {timeRemaining === 0 && (
        <span className="text-red-500 text-sm font-bold">
          Time&apos;s up! Submitting...
        </span>
      )}
    </div>
  );
};

Timer.propTypes = {
  durationMinutes: PropTypes.number.isRequired,
  onTimeUp: PropTypes.func.isRequired,
  testId: PropTypes.string.isRequired,
  userId: PropTypes.string,
};

export default Timer;
