import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { AuthStatus, User } from '../types/api';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (token: string) => void;
  logout: () => void;
  updateUser: (user: User) => void;
  authStatus: AuthStatus | null;
  setAuthStatus: (status: AuthStatus) => void;
  apiCall: (url: string, options?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Check if user is already authenticated
    const token = localStorage.getItem('token');
    if (token) {
      // Verify token with backend and fetch user data
      fetchUserData(token);
    } else {
      setIsLoading(false);
    }
  }, []);

  const fetchUserData = async (token: string) => {
    try {
      const response = await fetch(`${process.env.REACT_APP_API_URL || 'http://localhost:8000'}/auth/status`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const data = await response.json();
        setUser(data.user);
        setAuthStatus(data);
        
        // Trigger comprehensive sync on app load if user has connected integrations
        if (data.integrations && (data.integrations.google || data.integrations.hubspot)) {
          try {
            const syncResponse = await fetch('/integrations/initial-sync', {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({ force_refresh: true }),
            });

            if (syncResponse.ok) {
              const syncResult = await syncResponse.json();
            } else {
            }
          } catch (syncError) {
          }
        }
      } else {
        // Token is invalid, remove it
        localStorage.removeItem('token');
        setUser(null);
        setAuthStatus(null);
      }
    } catch (error) {
      console.error('Failed to fetch user data:', error);
      localStorage.removeItem('token');
      setUser(null);
      setAuthStatus(null);
    } finally {
      setIsLoading(false);
    }
  };

  const login = (token: string) => {
    localStorage.setItem('token', token);
    fetchUserData(token);
  };

  const logout = () => {
    localStorage.removeItem('token');
    setUser(null);
    setAuthStatus(null);
  };

  const updateUser = (userData: User) => {
    setUser(userData);
  };

  const apiCall = async (url: string, options: RequestInit = {}): Promise<Response> => {
    const baseUrl = process.env.REACT_APP_API_URL || 'http://localhost:8000';
    const fullUrl = url.startsWith('http') ? url : `${baseUrl}${url}`;
    
    const token = localStorage.getItem('token');
    if (token) {
      options.headers = {
        ...options.headers,
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      };
    }

    let response = await fetch(fullUrl, options);

    // If we get a 401 and have a token, try to refresh it
    if (response.status === 401 && token) {
      try {
        const refreshResponse = await fetch(`${baseUrl}/auth/refresh`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        });

        if (refreshResponse.ok) {
          const { access_token } = await refreshResponse.json();
          localStorage.setItem('token', access_token);
          
          // Retry the original request with the new token
          options.headers = {
            ...options.headers,
            'Authorization': `Bearer ${access_token}`,
          };
          response = await fetch(fullUrl, options);
        } else {
          // Refresh failed, logout user
          logout();
        }
      } catch (error) {
        console.error('Token refresh failed:', error);
        logout();
      }
    }

    return response;
  };

  const value: AuthContextType = {
    user,
    isAuthenticated: !!user,
    isLoading,
    login,
    logout,
    updateUser,
    authStatus,
    setAuthStatus,
    apiCall,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}; 