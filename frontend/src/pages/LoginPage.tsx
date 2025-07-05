import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';

export const LoginPage: React.FC = () => {
  const { isAuthenticated } = useAuth();

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const handleGoogleLogin = () => {
    // Redirect to Google OAuth
    window.location.href = `${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/auth/google/login`;
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
            Financial Agent
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            AI Assistant for Financial Advisors
          </p>
        </div>
        
        <div className="mt-8 space-y-6">
          <div>
            <button
              onClick={handleGoogleLogin}
              className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
            >
              <span className="absolute left-0 inset-y-0 flex items-center pl-3">
                <svg className="h-5 w-5 text-primary-500 group-hover:text-primary-400" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M18 10c0-3.866-3.582-7-8-7s-8 3.134-8 7c0 3.866 3.582 7 8 7s8-3.134 8-7z" />
                </svg>
              </span>
              Sign in with Google
            </button>
          </div>

          <div className="text-center">
            <p className="text-sm text-gray-500">
              Connect your Gmail, Calendar, and HubSpot to get started
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}; 