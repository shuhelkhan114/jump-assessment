import React, { createContext, useContext, useState, useEffect } from 'react';
import { AuthStatus, User } from '../types/api';
import { API_ENDPOINTS } from '../config/api';
import { fetchWithAuth } from '../utils/api';

interface AuthContextType {
    user: User | null;
    authStatus: AuthStatus | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    login: () => void;
    logout: () => void;
    checkAuthStatus: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
    children: React.ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [isLoading, setIsLoading] = useState(true);

    const checkAuthStatus = async () => {
        try {
            const response = await fetchWithAuth(API_ENDPOINTS.AUTH_STATUS);
            if (response.ok) {
                const data = await response.json();
                setUser(data.user);
                setAuthStatus(data);
                setIsAuthenticated(true);
                return true;
            } else {
                localStorage.removeItem('token');
                setUser(null);
                setAuthStatus(null);
                setIsAuthenticated(false);
                return false;
            }
        } catch (error) {
            console.error('Error checking auth status:', error);
            setIsAuthenticated(false);
            return false;
        } finally {
            setIsLoading(false);
        }
    };

    const login = () => {
        window.location.href = API_ENDPOINTS.AUTH_GOOGLE_LOGIN;
    };

    const logout = async () => {
        try {
            await fetchWithAuth(API_ENDPOINTS.AUTH_STATUS, {
                method: 'POST'
            });
        } catch (error) {
            console.error('Error during logout:', error);
        }
        localStorage.removeItem('token');
        setUser(null);
        setAuthStatus(null);
        setIsAuthenticated(false);
    };

    useEffect(() => {
        checkAuthStatus();
    }, []);

    const value = {
        user,
        authStatus,
        isAuthenticated,
        isLoading,
        login,
        logout,
        checkAuthStatus
    };

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
}; 