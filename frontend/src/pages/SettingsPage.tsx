import React from 'react';

export const SettingsPage: React.FC = () => {
  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Settings</h1>
      
      <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Account Settings</h2>
        <p className="text-gray-600">
          Settings will be available here.
        </p>
      </div>
    </div>
  );
}; 