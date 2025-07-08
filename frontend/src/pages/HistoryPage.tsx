import React, { useEffect, useState } from 'react';
import { API_ENDPOINTS } from '../config/api';
import { fetchWithAuth } from '../utils/api';

interface ChatSession {
    id: string;
    title: string;
    created_at: string;
}

const HistoryPage = () => {
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [loading, setLoading] = useState(true);

    const loadSessions = async () => {
        try {
            const response = await fetchWithAuth(API_ENDPOINTS.CHAT_SESSIONS);
            if (response.ok) {
                const data = await response.json();
                setSessions(data);
            }
        } catch (error) {
            console.error('Error loading sessions:', error);
        } finally {
            setLoading(false);
        }
    };

    const deleteSession = async (sessionId: string) => {
        try {
            const response = await fetchWithAuth(API_ENDPOINTS.CHAT_SESSION(sessionId), {
                method: 'DELETE'
            });
            if (response.ok) {
                setSessions(prev => prev.filter(session => session.id !== sessionId));
            }
        } catch (error) {
            console.error('Error deleting session:', error);
        }
    };

    useEffect(() => {
        loadSessions();
    }, []);

    if (loading) {
        return <div>Loading...</div>;
    }

    return (
        <div className="container mx-auto px-4 py-8">
            <h1 className="text-2xl font-bold mb-6">Chat History</h1>
            <div className="grid gap-4">
                {sessions.map(session => (
                    <div key={session.id} className="bg-white p-4 rounded shadow flex justify-between items-center">
                        <div>
                            <h2 className="font-semibold">{session.title || 'Untitled Session'}</h2>
                            <p className="text-sm text-gray-500">
                                {new Date(session.created_at).toLocaleDateString()}
                            </p>
                        </div>
                        <div className="flex gap-2">
                            <button
                                onClick={() => window.location.href = `/chat/${session.id}`}
                                className="px-3 py-1 bg-blue-500 text-white rounded hover:bg-blue-600"
                            >
                                View
                            </button>
                            <button
                                onClick={() => deleteSession(session.id)}
                                className="px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600"
                            >
                                Delete
                            </button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default HistoryPage; 