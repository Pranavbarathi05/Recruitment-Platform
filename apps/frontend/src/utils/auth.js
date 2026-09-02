/**
 * Test timer utilities
 *
 * These helpers manage test timer state in localStorage.
 * They use the user ID (passed as a parameter) to namespace keys.
 *
 * Authentication is handled entirely by the FastAPI backend via AuthContext.
 * This file does NOT manage authentication state.
 */

/**
 * Check if a test has been started for a given user.
 * @param {string} testId - The domain/test identifier
 * @param {string} userId - The user ID
 */
export const hasStartedTest = (testId, userId) => {
  if (!userId) return false;
  const testKey = `timer_${testId}_${userId}`;
  return !!localStorage.getItem(testKey);
};

/**
 * Check if a test has expired for a given user.
 * @param {string} testId - The domain/test identifier
 * @param {string} userId - The user ID
 */
export const isTestExpired = (testId, userId) => {
  if (!userId) return false;
  const testKey = `timer_${testId}_${userId}`;
  return localStorage.getItem(`${testKey}_expired`) === 'true';
};

/**
 * Get the status of a test for a given user.
 * @param {string} testId - The domain/test identifier
 * @param {string} userId - The user ID
 * @returns {'expired' | 'in_progress' | 'available'} Test status
 */
export const getTestStatus = (testId, userId) => {
  if (!userId) {
    return 'available';
  }

  if (isTestExpired(testId, userId)) {
    return 'expired';
  }

  if (hasStartedTest(testId, userId)) {
    return 'in_progress';
  }

  return 'available';
};
