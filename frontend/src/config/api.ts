export const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export const API_ENDPOINTS = {
    // Auth endpoints
    AUTH_STATUS: `${API_BASE_URL}/auth/status`,
    AUTH_GOOGLE_LOGIN: `${API_BASE_URL}/auth/google/login`,
    
    // Chat endpoints
    CHAT_SESSIONS: `${API_BASE_URL}/chat/sessions`,
    CHAT_SESSION: (sessionId: string) => `${API_BASE_URL}/chat/sessions/${sessionId}`,
    CHAT_HISTORY: (sessionId: string) => `${API_BASE_URL}/chat/sessions/${sessionId}/history`,
    CHAT_MESSAGE: (sessionId: string) => `${API_BASE_URL}/chat/sessions/${sessionId}/message`,
    
    // Integration endpoints
    INTEGRATION_STATUS: `${API_BASE_URL}/integrations/status`,
    INTEGRATION_HEALTH: `${API_BASE_URL}/integrations/health-check`,
    HUBSPOT_AUTH_URL: `${API_BASE_URL}/integrations/hubspot/auth-url`,
}; 