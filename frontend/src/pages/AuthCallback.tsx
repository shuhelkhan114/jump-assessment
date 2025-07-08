import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const AuthCallback = () => {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const { login, checkAuthStatus } = useAuth();

    useEffect(() => {
        const token = searchParams.get('token');
        const error = searchParams.get('error');

        const handleCallback = async () => {
            if (token) {
                // Store token if needed
                localStorage.setItem('token', token);
                // Check auth status which will set the user
                await checkAuthStatus();
                navigate('/', { replace: true });
            } else if (error) {
                navigate('/login', { replace: true });
            } else {
                navigate('/login', { replace: true });
            }
        };

        handleCallback();
    }, [searchParams, navigate, checkAuthStatus]);

    return (
        <div className="flex items-center justify-center min-h-screen">
            <div className="text-center">
                <h2 className="text-xl font-semibold mb-4">Authenticating...</h2>
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto"></div>
            </div>
        </div>
    );
};

export default AuthCallback; 