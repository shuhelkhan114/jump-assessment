import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';

interface SyncService {
  status: string;
  message: string;
}

interface SyncResults {
  [service: string]: SyncService;
}

interface HealthCheckResult {
  user_id: string;
  timestamp: string;
  overall_status: string;
  services: {
    [service: string]: {
      status: string;
      message: string;
    };
  };
}

interface SyncTask {
  task_id: string;
  status: string;
  ready: boolean;
  sync_results?: SyncResults;
  sync_triggered?: boolean;
}

const SyncStatusPanel: React.FC = () => {
  const { apiCall } = useAuth();
  const [healthStatus, setHealthStatus] = useState<HealthCheckResult | null>(null);
  const [syncTask, setSyncTask] = useState<SyncTask | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [isManualSyncing, setIsManualSyncing] = useState(false);
  const [lastSyncTime, setLastSyncTime] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  // Fetch health status
  const fetchHealthStatus = useCallback(async () => {
    try {
      const response = await apiCall('/integrations/health-check');
      
      if (response.ok) {
        const data = await response.json();
        setHealthStatus(data);
        setError(null);
      } else {
        throw new Error('Failed to fetch health status');
      }
    } catch (err) {
      setError('Failed to check sync health');
      console.error('Health check failed:', err);
    }
  }, [apiCall]);

  // Poll sync task status
  const pollSyncStatus = useCallback(async (taskId: string) => {
    try {
      const response = await apiCall(`/integrations/robust-sync/task-status/${taskId}`);
      
      if (response.ok) {
        const data = await response.json();
        setSyncTask(data);
        
        if (data.ready) {
          setIsPolling(false);
          setIsManualSyncing(false);
          setLastSyncTime(new Date().toLocaleTimeString());
          
          // Refresh health status after sync completion
          setTimeout(fetchHealthStatus, 1000);
        }
      }
    } catch (err) {
      console.error('Failed to poll sync status:', err);
    }
  }, [apiCall, fetchHealthStatus]);

  // Start sync
  const handleManualSync = async (services?: string[]) => {
    setIsManualSyncing(true);
    setError(null);
    
    try {
      const body: any = { force_refresh: true };
      if (services && services.length > 0) {
        body.services = services;
      }
      
      const response = await apiCall('/integrations/robust-sync', {
        method: 'POST',
        body: JSON.stringify(body)
      });
      
      if (response.ok) {
        const data = await response.json();
        setSyncTask({ task_id: data.task_id, status: 'PENDING', ready: false });
        setIsPolling(true);
      } else {
        throw new Error('Failed to start sync');
      }
    } catch (err) {
      setError('Failed to start sync');
      setIsManualSyncing(false);
      console.error('Manual sync failed:', err);
    }
  };

  // Refresh tokens
  const handleRefreshTokens = async () => {
    try {
      const response = await apiCall('/integrations/refresh-tokens', {
        method: 'POST'
      });
      
      if (response.ok) {
        await fetchHealthStatus();
      } else {
        throw new Error('Failed to refresh tokens');
      }
    } catch (err) {
      setError('Failed to refresh tokens');
      console.error('Token refresh failed:', err);
    }
  };

  // Auto-load health status on mount
  useEffect(() => {
    fetchHealthStatus();
    
    // Set up periodic health checks every 30 seconds
    const interval = setInterval(fetchHealthStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchHealthStatus]);

  // Poll sync status when task is active
  useEffect(() => {
    if (isPolling && syncTask?.task_id) {
      const interval = setInterval(() => {
        pollSyncStatus(syncTask.task_id);
      }, 2000);
      
      return () => clearInterval(interval);
    }
  }, [isPolling, syncTask?.task_id, pollSyncStatus]);

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'healthy':
      case 'success':
        return 'text-green-600';
      case 'degraded':
      case 'partial':
        return 'text-yellow-600';
      case 'error':
      case 'failed':
        return 'text-red-600';
      default:
        return 'text-gray-600';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case 'healthy':
      case 'success':
        return '✅';
      case 'degraded':
      case 'partial':
        return '⚠️';
      case 'error':
      case 'failed':
        return '❌';
      default:
        return '🔄';
    }
  };

  const renderSyncResults = () => {
    if (!syncTask?.sync_results) return null;
    
    return (
      <div className="mt-3 space-y-2">
        <div className="text-sm font-medium text-gray-700">Sync Results:</div>
        {Object.entries(syncTask.sync_results).map(([service, result]) => (
          <div key={service} className="flex items-center justify-between bg-gray-50 rounded px-3 py-2">
            <div className="flex items-center space-x-2">
              <span className="capitalize font-medium">{service}</span>
              <span>{getStatusIcon(result.status)}</span>
            </div>
            <span className={`text-sm ${getStatusColor(result.status)}`}>
              {result.status}
            </span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
      {/* Header */}
      <div 
        className="flex items-center justify-between p-4 cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-2">
            <span className="text-lg">
              {healthStatus ? getStatusIcon(healthStatus.overall_status) : '🔄'}
            </span>
            <h3 className="font-semibold text-gray-900">Sync Status</h3>
          </div>
          
          {healthStatus && (
            <span className={`text-sm font-medium ${getStatusColor(healthStatus.overall_status)}`}>
              {healthStatus.overall_status}
            </span>
          )}
        </div>
        
        <div className="flex items-center space-x-2">
          {lastSyncTime && (
            <span className="text-xs text-gray-500">
              Last: {lastSyncTime}
            </span>
          )}
          
          <svg 
            className={`w-4 h-4 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
            fill="currentColor" 
            viewBox="0 0 20 20"
          >
            <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </div>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="border-t border-gray-200 p-4">
          {/* Error Display */}
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
              {error}
            </div>
          )}

          {/* Service Status */}
          {healthStatus?.services && (
            <div className="mb-4">
              <div className="text-sm font-medium text-gray-700 mb-2">Service Health:</div>
              <div className="space-y-2">
                {Object.entries(healthStatus.services).map(([service, status]) => (
                  <div key={service} className="flex items-center justify-between bg-gray-50 rounded px-3 py-2">
                    <div className="flex items-center space-x-2">
                      <span className="capitalize font-medium">{service}</span>
                      <span>{getStatusIcon(status.status)}</span>
                    </div>
                    <span className={`text-sm ${getStatusColor(status.status)}`}>
                      {status.message}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sync Progress */}
          {isManualSyncing && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded">
              <div className="flex items-center space-x-2">
                <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                <span className="text-blue-700 font-medium">
                  {syncTask?.status === 'PENDING' ? 'Starting sync...' : 
                   syncTask?.status === 'PROGRESS' ? 'Syncing data...' : 
                   'Processing...'}
                </span>
              </div>
            </div>
          )}

          {/* Sync Results */}
          {renderSyncResults()}

          {/* Action Buttons */}
          <div className="flex flex-wrap gap-2 mt-4">
            <button
              onClick={() => handleManualSync()}
              disabled={isManualSyncing}
              className="flex items-center space-x-2 px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
              </svg>
              <span>Sync All</span>
            </button>

            <button
              onClick={() => handleManualSync(['gmail'])}
              disabled={isManualSyncing}
              className="flex items-center space-x-2 px-3 py-2 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 text-sm"
            >
              <span>📧</span>
              <span>Gmail</span>
            </button>

            <button
              onClick={() => handleManualSync(['calendar'])}
              disabled={isManualSyncing}
              className="flex items-center space-x-2 px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              <span>📅</span>
              <span>Calendar</span>
            </button>

            <button
              onClick={() => handleManualSync(['hubspot'])}
              disabled={isManualSyncing}
              className="flex items-center space-x-2 px-3 py-2 bg-orange-600 text-white rounded hover:bg-orange-700 disabled:opacity-50 text-sm"
            >
              <span>🔗</span>
              <span>HubSpot</span>
            </button>

            <button
              onClick={handleRefreshTokens}
              className="flex items-center space-x-2 px-3 py-2 bg-gray-600 text-white rounded hover:bg-gray-700 text-sm"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-8.293l-3-3a1 1 0 00-1.414 1.414L10.586 9H7a1 1 0 100 2h3.586l-1.293 1.293a1 1 0 101.414 1.414l3-3a1 1 0 000-1.414z" clipRule="evenodd" />
              </svg>
              <span>Refresh Tokens</span>
            </button>

            <button
              onClick={fetchHealthStatus}
              className="flex items-center space-x-2 px-3 py-2 bg-green-600 text-white rounded hover:bg-green-700 text-sm"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
              </svg>
              <span>Check Health</span>
            </button>
          </div>

          {/* Last Updated */}
          {healthStatus?.timestamp && (
            <div className="text-xs text-gray-500 mt-3">
              Last checked: {new Date(healthStatus.timestamp).toLocaleString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default SyncStatusPanel; 