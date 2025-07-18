import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { ChatResponse, ConversationHistory, ToolResult } from '../types/api';
import { API_ENDPOINTS } from '../config/api';
import { fetchWithAuth } from '../utils/api';
import { useAuth } from '../contexts/AuthContext';

// Enhanced message type to include tool results
interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  tool_results?: ToolResult[];
}

// HubSpot Integration Component
const HubSpotIntegration: React.FC = () => {
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    checkIntegrationStatus();
  }, []);

  const checkIntegrationStatus = async () => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.INTEGRATION_STATUS);
      if (response.ok) {
        const data = await response.json();
        setIsConnected(data.hubspot);
      }
    } catch (error) {
      console.error('Error checking integration status:', error);
    }
  };

  const handleConnect = async () => {
    setIsLoading(true);
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.HUBSPOT_AUTH_URL);
      if (response.ok) {
        const data = await response.json();
        window.location.href = data.auth_url;
      }
    } catch (error) {
      console.error('Error getting Hubspot auth URL:', error);
    } finally {
      setIsLoading(false);
    }
  };

  if (isConnected) {
    return (
      <div className="flex items-center space-x-2 text-green-600">
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
        </svg>
        <span className="text-sm">HubSpot Connected</span>
      </div>
    );
  }

  return (
    <button
      onClick={handleConnect}
      disabled={isLoading}
      className="flex items-center space-x-2 px-3 py-1 bg-orange-500 text-white rounded hover:bg-orange-600 disabled:opacity-50 text-sm"
    >
      {isLoading ? (
        <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
      ) : (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z" />
        </svg>
      )}
      <span>Connect HubSpot</span>
    </button>
  );
};

export const ChatPage: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [sessionTitle, setSessionTitle] = useState<string>('');
  const [isCreatingNewSession, setIsCreatingNewSession] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Load session from URL parameters
  useEffect(() => {
    const sessionId = searchParams.get('session');
    console.log('Session ID from URL:', sessionId); // Debug log
    if (sessionId) {
      setCurrentSessionId(sessionId);
      loadSessionHistory(sessionId);
    } else {
      // If no session ID in URL, clear the current session
      setCurrentSessionId(null);
      setMessages([]);
      setSessionTitle('');
    }
  }, [searchParams]);

  // Load conversation history when session changes
  useEffect(() => {
    console.log('Current session ID changed:', currentSessionId); // Debug log
    if (currentSessionId && !isCreatingNewSession) {
      loadSessionHistory(currentSessionId);
    }
  }, [currentSessionId, isCreatingNewSession]);

  const loadSessionHistory = async (sessionId: string) => {
    console.log('Loading session history for:', sessionId); // Debug log
    setIsLoadingSession(true);
    try {
      // Load session details
      const sessionResponse = await fetchWithAuth(API_ENDPOINTS.CHAT_SESSION(sessionId));
      console.log('Session details response:', sessionResponse.status); // Debug log

      if (sessionResponse.ok) {
        const session = await sessionResponse.json();
        console.log('Session details:', session); // Debug log
        setSessionTitle(session.title);
      } else {
        console.error('Failed to load session details:', sessionResponse.status);
        // If session not found, clear the session
        if (sessionResponse.status === 404) {
          setCurrentSessionId(null);
          navigate('/chat', { replace: true });
          return;
        }
      }

      // Load session history
      const historyResponse = await fetchWithAuth(API_ENDPOINTS.CHAT_HISTORY(sessionId));
      console.log('History response:', historyResponse.status); // Debug log

      if (historyResponse.ok) {
        const history: ConversationHistory[] = await historyResponse.json();
        console.log('Loaded history:', history); // Debug log
        const formattedMessages: ChatMessage[] = history.reverse().flatMap(conv => [
          { role: 'user' as const, content: conv.message },
          { role: 'assistant' as const, content: conv.response }
        ]);
        setMessages(formattedMessages);
      } else {
        console.error('Failed to load history:', historyResponse.status);
      }
    } catch (error) {
      console.error('Failed to load session history:', error);
    } finally {
      setIsLoadingSession(false);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMessage.trim()) return;

    const userMessage = inputMessage.trim();
    setInputMessage('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      let sessionId = currentSessionId;
      console.log('Initial sessionId:', sessionId); // Debug log
      let isNewSession = false;
      
      // If no session exists, create one first
      if (!sessionId) {
        console.log('Creating new session...'); // Debug log
        setIsCreatingNewSession(true);
        isNewSession = true;
        
        const sessionResponse = await fetchWithAuth(API_ENDPOINTS.CHAT_SESSIONS, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({})
        });

        console.log('Session creation response status:', sessionResponse.status); // Debug log

        if (!sessionResponse.ok) {
          throw new Error('Failed to create chat session');
        }

        const newSession = await sessionResponse.json();
        console.log('New session response:', newSession); // Debug log

        if (!newSession || !newSession.id) {
          throw new Error('Invalid session response');
        }

        sessionId = newSession.id;
        console.log('New sessionId:', sessionId); // Debug log
        
        // Set the session ID first
        setCurrentSessionId(sessionId);
        
        // Then update URL (this will trigger the useEffect to load session)
        navigate(`/chat?session=${sessionId}`, { replace: true });
        
        // Set initial title
        setSessionTitle(newSession.title || 'New Chat');
      }

      // Ensure we have a valid session ID before sending message
      if (!sessionId) {
        throw new Error('No valid session ID available');
      }

      console.log('Using sessionId for message:', sessionId); // Debug log
      console.log('API endpoint:', API_ENDPOINTS.CHAT_MESSAGE(sessionId)); // Debug log

      // Send message to the session
      const response = await fetchWithAuth(API_ENDPOINTS.CHAT_MESSAGE(sessionId), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: userMessage })
      });

      console.log('Message send response status:', response.status); // Debug log

      if (response.ok) {
        const data: ChatResponse = await response.json();
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: data.response,
          tool_results: data.tool_results 
        }]);

        // If this was the first message (creating a new session), refresh the session title
        if (isNewSession) {
          try {
            console.log('Refreshing session title for sessionId:', sessionId); // Debug log
            const sessionResponse = await fetchWithAuth(API_ENDPOINTS.CHAT_SESSION(sessionId));
            if (sessionResponse.ok) {
              const session = await sessionResponse.json();
              setSessionTitle(session.title);
            }
          } catch (error) {
            console.error('Failed to refresh session title:', error);
          }
          // Reset the creating new session flag
          setIsCreatingNewSession(false);
        }
      } else {
        console.error('Failed to send message:', response.status);
        setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
      }
    } catch (error) {
      console.error('Error sending message:', error);
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
      // Reset the creating new session flag in case of error
      if (isCreatingNewSession) {
        setIsCreatingNewSession(false);
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-full bg-white">
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Chat Header */}
        <div className="border-b border-gray-200 p-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold text-gray-900">
                {currentSessionId ? (sessionTitle || 'AI Assistant') : 'AI Assistant'}
              </h1>
              <p className="text-sm text-gray-600">
                {currentSessionId 
                  ? 'Ask me about your clients, emails, or schedule meetings'
                  : 'Select a chat thread to start conversation'
                }
              </p>
            </div>
            <div className="flex items-center space-x-3">
              <HubSpotIntegration />
            </div>
          </div>
        </div>

        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {!currentSessionId ? (
            <div className="text-center py-8">
              <p className="text-gray-500 mb-4">Ready to start a new conversation</p>
              <p className="text-sm text-gray-400 mb-6">
                Start typing below to begin your chat with the AI assistant
              </p>
              <div className="flex justify-center">
                <button
                  onClick={() => navigate('/history')}
                  className="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700"
                >
                  View History
                </button>
              </div>
            </div>
          ) : isLoadingSession ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-gray-500">Start a conversation with your AI assistant</p>
              <p className="text-sm text-gray-400 mt-2">
                Try asking: "Who mentioned their kid plays baseball?" or "Schedule a meeting with John"
              </p>
            </div>
          ) : (
            messages.map((message, index) => (
              <div
                key={index}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-md lg:max-w-2xl px-4 py-3 rounded-lg ${
                    message.role === 'user'
                      ? 'bg-primary-600 text-white'
                      : 'bg-gray-100 text-gray-900'
                  }`}
                >
                  <ReactMarkdown 
                    className={`prose prose-sm ${message.role === 'user' ? 'prose-invert' : ''} max-w-none`}
                    components={{
                      // Custom styling for markdown elements
                      p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                      ul: ({ children }) => <ul className="list-disc list-outside ml-4 mb-2 space-y-1">{children}</ul>,
                      ol: ({ children }) => <ol className="list-decimal list-outside ml-4 mb-2 space-y-1">{children}</ol>,
                      li: ({ children }) => <li className="mb-0 pl-1">{children}</li>,
                      strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                      em: ({ children }) => <em className="italic">{children}</em>,
                      code: ({ children }) => (
                        <code className={`px-1 py-0.5 rounded text-sm font-mono ${
                          message.role === 'user' 
                            ? 'bg-primary-700 text-white' 
                            : 'bg-gray-200 text-gray-800'
                        }`}>
                          {children}
                        </code>
                      ),
                      h1: ({ children }) => <h1 className="text-lg font-bold mb-2">{children}</h1>,
                      h2: ({ children }) => <h2 className="text-base font-bold mb-2">{children}</h2>,
                      h3: ({ children }) => <h3 className="text-sm font-bold mb-1">{children}</h3>,
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                  
                </div>
              </div>
            ))
          )}
          
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-gray-100 text-gray-900 max-w-md lg:max-w-2xl px-4 py-3 rounded-lg">
                <div className="flex items-center space-x-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-600"></div>
                  <span>Thinking...</span>
                </div>
              </div>
            </div>
          )}
          
          {/* Scroll target */}
          <div ref={messagesEndRef} />
        </div>

        {/* Chat Input */}
        <form onSubmit={handleSendMessage} className="border-t border-gray-200 p-4">
          <div className="flex space-x-4">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              placeholder="Type your message..."
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !inputMessage.trim()}
              className="px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Send
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}; 