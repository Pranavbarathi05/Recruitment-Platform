import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';


/**
 * Hero Component
 * 
 * A hero section for the landing page featuring the DSC logo and call-to-action buttons.
 * 
 * @param {Object} props - Component props
 * @param {string} props.title - Main title text
 * @param {string} props.subtitle - Subtitle/chapter name with colored styling
 * @param {string} props.description - Description text
 * @param {string} props.heroImage - URL/path to the hero image/logo
 * @param {Array} props.ctaButtons - Array of CTA button objects { text: string, href: string, variant: 'primary' | 'secondary' }
 */
const Hero = ({
  title = 'Developer Student Club',
  subtitle = 'JSSSTU Chapter',
  description = 'Building a community of student developers, fostering innovation and creating impact through technology.',
  heroImage = '/logo-hero.png',
  ctaButtons = [
    { text: 'Join Us', href: '/login', variant: 'primary' },
    { text: 'Our Events', href: '/domains', variant: 'secondary' },
  ],
}) => {
  const buttonStyles = {
    primary: 'bg-blue-600 hover:bg-blue-700 text-white',
    secondary: 'bg-yellow-500 hover:bg-yellow-600 text-white',
  };

  return (
    <section className="relative w-full min-h-[90vh] flex items-center justify-center overflow-hidden bg-theme-primary py-16 px-4 sm:px-6 lg:px-8">
      {/* Background decorative elements */}
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute top-0 right-0 md:w-2/5 w-1/2 h-1/2 bg-blue-600 opacity-10" />
        <div className="absolute bottom-0 left-0 md:w-2/5 w-1/2 h-1/2 bg-yellow-500 opacity-10" />
      </div>

      <div className="relative z-20 max-w-7xl mx-auto flex flex-col lg:flex-row items-center justify-between gap-12">
        {/* Text Content */}
        <div className="flex-1 text-center lg:text-left">
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-theme-primary leading-tight mb-6 tracking-tight">
            {title}
            <span className="block text-blue-500 mt-2">{subtitle}</span>
          </h1>

          <p className="text-lg md:text-xl text-theme-muted max-w-2xl mb-8 tracking-tight">
            {description}
          </p>

          {/* CTA Buttons */}
          <div className="flex flex-wrap gap-4 justify-center lg:justify-start">
            {ctaButtons.map((button, index) => (
              <Link
                key={index}
                to={button.href}
                className={`flex items-center gap-2 font-bold px-6 py-3 rounded-full text-base transition duration-200 ${
                  buttonStyles[button.variant] || buttonStyles.primary
                }`}
              >
                {button.text}
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M7 17L17 7M17 7H7M17 7v10"
                  />
                </svg>
              </Link>
            ))}
          </div>
        </div>

        {/* Hero Image/Logo */}
        <div className="flex-1 flex justify-center items-center">
          <div className="relative w-full max-w-md p-6 flex items-center justify-center">
            <div className="w-full aspect-square relative overflow-visible">
              {/* Floating animation for the logo */}
              <img
                src={heroImage}
                alt="DSC Logo"
                className="w-full h-auto object-contain animate-float"
              />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

Hero.propTypes = {
  title: PropTypes.string,
  subtitle: PropTypes.string,
  description: PropTypes.string,
  heroImage: PropTypes.string,
  ctaButtons: PropTypes.arrayOf(
    PropTypes.shape({
      text: PropTypes.string.isRequired,
      href: PropTypes.string.isRequired,
      variant: PropTypes.oneOf(['primary', 'secondary']),
    })
  ),
};

export default Hero;
