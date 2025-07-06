import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export const Navbar: React.FC = () => {
  const { logout } = useAuth();
  const location = useLocation();
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<'idle' | 'success' | 'error'>('idle');

  const isActive = (path: string) => location.pathname === path;

  const handleSync = async () => {
    try {
      setIsSyncing(true);
      setSyncStatus('idle');
      
      const token = localStorage.getItem('token');
      const response = await fetch('http://localhost:8000/integrations/sync', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const result = await response.json();
        setSyncStatus('success');
        console.log('Sync started:', result);
        
        // Reset status after 3 seconds
        setTimeout(() => setSyncStatus('idle'), 3000);
      } else {
        setSyncStatus('error');
        setTimeout(() => setSyncStatus('idle'), 3000);
      }
    } catch (error) {
      console.error('Sync failed:', error);
      setSyncStatus('error');
      setTimeout(() => setSyncStatus('idle'), 3000);
    } finally {
      setIsSyncing(false);
    }
  };

  const getSyncButtonClass = () => {
    const baseClass = "px-3 py-2 rounded-md text-sm font-medium flex items-center space-x-1";
    
    if (isSyncing) {
      return `${baseClass} bg-blue-100 text-blue-700 cursor-not-allowed`;
    }
    
    if (syncStatus === 'success') {
      return `${baseClass} bg-green-100 text-green-700`;
    }
    
    if (syncStatus === 'error') {
      return `${baseClass} bg-red-100 text-red-700`;
    }
    
    return `${baseClass} text-gray-600 hover:text-gray-900 hover:bg-gray-100`;
  };

  return (
    <nav className="bg-white shadow-sm border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex items-center">
            <Link to="/" className="text-xl font-bold text-primary-600">
              Financial Agent
            </Link>
          </div>

          <div className="flex items-center space-x-4">
            <Link
              to="/chat"
              className={`px-3 py-2 rounded-md text-sm font-medium ${
                isActive('/chat') || isActive('/')
                  ? 'bg-primary-100 text-primary-700'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Chat
            </Link>

            <button
              onClick={handleSync}
              disabled={isSyncing}
              className={getSyncButtonClass()}
              title="Sync data from connected integrations"
            >
              <svg
                className={`w-4 h-4 ${isSyncing ? 'animate-spin' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              <span>
                {isSyncing ? 'Syncing...' : 
                 syncStatus === 'success' ? 'Synced!' :
                 syncStatus === 'error' ? 'Error' : 'Sync'}
              </span>
            </button>

            <button
              onClick={logout}
              className="text-gray-600 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium"
            >
              Logout
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}; 