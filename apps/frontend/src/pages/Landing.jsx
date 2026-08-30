import Hero from '../components/sections/Hero';

/**
 * Landing Page
 * 
 * The main landing page for the DSC Recruitment Platform.
 * Features a hero section with DSC branding and call-to-action buttons.
 */
const Landing = () => {
  return (
    <main className="min-h-screen bg-theme-primary">
      <Hero />
    </main>
  );
};

export default Landing;
