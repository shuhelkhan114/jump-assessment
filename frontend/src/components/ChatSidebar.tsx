import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_ENDPOINTS } from '../config/api';
import { fetchWithAuth } from '../utils/api';

interface ChatSession {
    id: string;
    title: string;
    created_at: string;
}

interface ChatSidebarProps {
    currentSessionId?: string;
    onSessionSelect: (sessionId: string) => void;
}

const ChatSidebar: React.FC<ChatSidebarProps> = ({ currentSessionId, onSessionSelect }) => {
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const navigate = useNavigate();

    const loadSessions = async () => {
        try {
            const response = await fetchWithAuth(API_ENDPOINTS.CHAT_SESSIONS);
            if (response.ok) {
                const data = await response.json();
                setSessions(data);
            }
        } catch (error) {
            console.error('Error loading sessions:', error);
        }
    };

    const createNewSession = async () => {
        try {
            const response = await fetchWithAuth(API_ENDPOINTS.CHAT_SESSIONS, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
            });

            if (response.ok) {
                const session = await response.json();
                setSessions(prev => [session, ...prev]);
                onSessionSelect(session.id);
            }
        } catch (error) {
            console.error('Error creating new session:', error);
        }
    };

    const deleteSession = async (sessionId: string) => {
        try {
            const response = await fetchWithAuth(API_ENDPOINTS.CHAT_SESSION(sessionId), {
                method: 'DELETE',
            });

            if (response.ok) {
                setSessions(prev => prev.filter(s => s.id !== sessionId));
                if (sessionId === currentSessionId) {
                    navigate('/chat');
                }
            }
        } catch (error) {
            console.error('Error deleting session:', error);
        }
    };

    useEffect(() => {
        loadSessions();
    }, []);

    return (
        <div className="w-64 bg-gray-50 border-r border-gray-200 p-4 flex flex-col h-full">
            <button
                onClick={createNewSession}
                className="w-full mb-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
                New Chat
            </button>
            
            <div className="flex-1 overflow-y-auto">
                {sessions.map(session => (
                    <div
                        key={session.id}
                        className={`p-3 mb-2 rounded cursor-pointer flex justify-between items-center ${
                            session.id === currentSessionId ? 'bg-blue-100' : 'hover:bg-gray-100'
                        }`}
                    >
                        <div
                            className="flex-1 truncate"
                            onClick={() => onSessionSelect(session.id)}
                        >
                            {session.title || 'New Chat'}
                        </div>
                        <button
                            onClick={() => deleteSession(session.id)}
                            className="ml-2 text-gray-500 hover:text-red-500"
                        >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default ChatSidebar; 