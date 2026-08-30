/**
 * Dashboard Page
 * 
 * A placeholder dashboard page shown after login.
 * This demonstrates the routed pages after the Login page.
 */
const Dashboard = () => {
  return (
    <main className="min-h-screen bg-theme-primary py-16 px-4">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-theme-primary mb-4">Dashboard</h1>
          <p className="text-theme-secondary text-lg">
            Welcome to the DSC Recruitment Platform Dashboard.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-theme-secondary rounded-lg p-6">
            <h3 className="text-xl font-bold text-theme-primary mb-2">Applications</h3>
            <p className="text-3xl font-bold text-blue-500">0</p>
            <p className="text-theme-secondary mt-2">Pending applications</p>
          </div>

          <div className="bg-theme-secondary rounded-lg p-6">
            <h3 className="text-xl font-bold text-theme-primary mb-2">Interviews</h3>
            <p className="text-3xl font-bold text-green-500">0</p>
            <p className="text-theme-secondary mt-2">Scheduled interviews</p>
          </div>

          <div className="bg-theme-secondary rounded-lg p-6">
            <h3 className="text-xl font-bold text-theme-primary mb-2">Status</h3>
            <p className="text-3xl font-bold text-yellow-500">Active</p>
            <p className="text-theme-secondary mt-2">Recruitment status</p>
          </div>
        </div>
      </div>
    </main>
  );
};

export default Dashboard;
