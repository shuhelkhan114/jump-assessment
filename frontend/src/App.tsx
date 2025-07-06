import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from 'react-query';
import { AuthProvider } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { Navbar } from './components/Navbar';
import { LoginPage } from './pages/LoginPage';
import { ChatPage } from './pages/ChatPage';
import { HistoryPage } from './pages/HistoryPage';
import { AuthCallback } from './pages/AuthCallback';

import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function App(): JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <div className="min-h-screen bg-gray-50">
            <Routes>
              {/* Public routes */}
              <Route path="/login" element={<LoginPage />} />
              <Route path="/auth/callback" element={<AuthCallback />} />
              <Route path="/auth/hubspot/success" element={<div>HubSpot Connected Successfully! <a href="/chat">Return to Chat</a></div>} />
              <Route path="/auth/error" element={<div>Authentication Error</div>} />
              
              {/* Protected routes */}
              <Route path="/" element={
                <ProtectedRoute>
                  <div className="flex flex-col h-screen">
                    <Navbar />
                    <main className="flex-1 overflow-hidden">
                      <ChatPage />
                    </main>
                  </div>
                </ProtectedRoute>
              } />
              
              <Route path="/chat" element={
                <ProtectedRoute>
                  <div className="flex flex-col h-screen">
                    <Navbar />
                    <main className="flex-1 overflow-hidden">
                      <ChatPage />
                    </main>
                  </div>
                </ProtectedRoute>
              } />
              
              <Route path="/history" element={
                <ProtectedRoute>
                  <div className="flex flex-col h-screen">
                    <Navbar />
                    <main className="flex-1 overflow-y-auto">
                      <HistoryPage />
                    </main>
                  </div>
                </ProtectedRoute>
              } />

            </Routes>
          </div>
        </Router>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App; 