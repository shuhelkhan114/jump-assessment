import React from 'react';

export const IntegrationsPage: React.FC = () => {
  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Integrations</h1>
      
      <div className="grid gap-6 md:grid-cols-2">
        {/* Gmail Integration */}
        <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Gmail</h2>
          <p className="text-gray-600 mb-4">
            Connect your Gmail account to enable email analysis and automation.
          </p>
          <button className="btn btn-primary">
            Connect Gmail
          </button>
        </div>

        {/* HubSpot Integration */}
        <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">HubSpot</h2>
          <p className="text-gray-600 mb-4">
            Connect your HubSpot CRM to sync contacts and notes.
          </p>
          <button className="btn btn-primary">
            Connect HubSpot
          </button>
        </div>
      </div>
    </div>
  );
}; 