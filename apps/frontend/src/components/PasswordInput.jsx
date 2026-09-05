import { useState } from 'react';

/**
 * PasswordInput
 *
 * Text input for passwords with a visibility toggle (eye / eye-off).
 * The toggle is a `type="button"` so it never submits the surrounding form,
 * and it carries an appropriate aria-label ("Show password" / "Hide password")
 * plus aria-pressed so the visible state is exposed to assistive technology.
 *
 * Styling matches the existing auth-form inputs (see Login.jsx / Signup.jsx);
 * `className` is forwarded so callers keep full control of sizing/appearance.
 */
const PasswordInput = ({
  id,
  value,
  onChange,
  placeholder,
  className = 'w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary placeholder-theme focus:outline-none focus:ring-2 focus:ring-blue-500',
  ...rest
}) => {
  const [showPassword, setShowPassword] = useState(false);

  return (
    <div className="relative">
      <input
        type={showPassword ? 'text' : 'password'}
        id={id}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className={`${className} pr-11`}
        {...rest}
      />
      <button
        type="button"
        onClick={() => setShowPassword((prev) => !prev)}
        aria-label={showPassword ? 'Hide password' : 'Show password'}
        aria-pressed={showPassword}
        className="absolute inset-y-0 right-0 flex items-center px-3 text-theme-muted hover:text-theme-primary focus:outline-none focus:ring-2 focus:ring-blue-500 rounded-r-lg"
      >
        {showPassword ? (
          // Eye-off (password hidden)
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
          </svg>
        ) : (
          // Eye (password visible)
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
          </svg>
        )}
      </button>
    </div>
  );
};

export default PasswordInput;