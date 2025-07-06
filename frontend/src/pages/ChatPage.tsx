import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { ChatResponse, ConversationHistory, ToolResult } from '../types/api';
import { ChatSidebar } from '../components/ChatSidebar';

// Enhanced message type to include tool results
interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  tool_results?: ToolResult[];
}

// Tool Results Debug Component - Self-contained with its own toggle
const ToolResultsDebug: React.FC<{ toolResults: ToolResult[] }> = ({ toolResults }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!toolResults || toolResults.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 border-t border-gray-200 pt-3">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center space-x-2 text-xs text-gray-600 hover:text-gray-800 transition-colors"
      >
        <svg 
          className={`w-3 h-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`} 
          fill="currentColor" 
          viewBox="0 0 20 20"
        >
          <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 111.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
        </svg>
        <span className="font-medium">
          Debug Info ({toolResults.length} action{toolResults.length !== 1 ? 's' : ''})
        </span>
        <span className="text-gray-400">
          {isExpanded ? 'Hide' : 'Show'}
        </span>
      </button>
      
      {isExpanded && (
        <div className="mt-2 space-y-2">
          {toolResults.map((result, index) => (
            <div key={index} className="bg-gray-50 rounded p-3 text-xs">
              <div className="flex items-center space-x-2 mb-2">
                <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                  result.status === 'success' 
                    ? 'bg-green-100 text-green-800' 
                    : 'bg-red-100 text-red-800'
                }`}>
                  {result.status === 'success' ? '✅' : '❌'} {result.tool}
                </span>
              </div>
              
              {result.status === 'success' && result.result && (
                <div>
                  <div className="font-medium text-gray-700 mb-1">Result:</div>
                  <pre className="text-xs text-gray-600 whitespace-pre-wrap bg-white p-2 rounded border overflow-x-auto">
                    {JSON.stringify(result.result, null, 2)}
                  </pre>
                </div>
              )}
              
              {result.status === 'error' && result.error && (
                <div>
                  <div className="font-medium text-red-700 mb-1">Error:</div>
                  <div className="text-red-600 bg-red-50 p-2 rounded">
                    {result.error}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// HubSpot Integration Component
const HubSpotIntegration: React.FC = () => {
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    checkIntegrationStatus();
  }, []);

  const checkIntegrationStatus = async () => {
    try {
      const response = await fetch('/integrations/status', {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });
      if (response.ok) {
        const data = await response.json();
        setIsConnected(data.hubspot);
      }
    } catch (error) {
      console.error('Failed to check integration status:', error);
    }
  };

  const handleConnect = async () => {
    setIsLoading(true);
    try {
      const response = await fetch('/integrations/hubspot/auth-url', {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });
      if (response.ok) {
        const data = await response.json();
        window.location.href = data.auth_url;
      }
    } catch (error) {
      console.error('Failed to get HubSpot auth URL:', error);
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
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Load conversation history when session changes
  useEffect(() => {
    if (currentSessionId) {
      loadSessionHistory(currentSessionId);
    }
  }, [currentSessionId]);

  const loadSessionHistory = async (sessionId: string) => {
    setIsLoadingSession(true);
    try {
      const response = await fetch(`/chat/sessions/${sessionId}/history`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });

      if (response.ok) {
        const history: ConversationHistory[] = await response.json();
        const formattedMessages: ChatMessage[] = history.reverse().flatMap(conv => [
          { role: 'user' as const, content: conv.message },
          { role: 'assistant' as const, content: conv.response }
        ]);
        setMessages(formattedMessages);
      }
    } catch (error) {
      console.error('Failed to load session history:', error);
    } finally {
      setIsLoadingSession(false);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMessage.trim() || !currentSessionId) return;

    const userMessage = inputMessage.trim();
    setInputMessage('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      // Call session-specific message endpoint
      const response = await fetch(`/chat/sessions/${currentSessionId}/message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify({ message: userMessage })
      });

      if (response.ok) {
        const data: ChatResponse = await response.json();
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: data.response,
          tool_results: data.tool_results 
        }]);
      } else {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
      }
    } catch (error) {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSessionSelect = (sessionId: string) => {
    setCurrentSessionId(sessionId);
  };

  const handleNewChat = () => {
    setMessages([]);
    setCurrentSessionId(null);
  };

  const handleDeleteSession = (sessionId: string) => {
    if (currentSessionId === sessionId) {
      setMessages([]);
      setCurrentSessionId(null);
    }
  };

  const handleRenameSession = (sessionId: string, newTitle: string) => {
    // Session title updated - no additional action needed for now
    console.log(`Session ${sessionId} renamed to: ${newTitle}`);
  };

  const createNewSessionAndSelect = async () => {
    try {
      const response = await fetch('/chat/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify({})
      });

      if (response.ok) {
        const newSession = await response.json();
        setCurrentSessionId(newSession.id);
        setMessages([]);
      }
    } catch (error) {
      console.error('Failed to create new session:', error);
    }
  };

  // Create initial session if none exists
  useEffect(() => {
    if (!currentSessionId) {
      createNewSessionAndSelect();
    }
  }, []);

  return (
    <div className="flex h-full bg-white">
      {/* Chat Sidebar */}
      <ChatSidebar
        currentSessionId={currentSessionId || undefined}
        onSessionSelect={handleSessionSelect}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onRenameSession={handleRenameSession}
      />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Chat Header */}
        <div className="border-b border-gray-200 p-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold text-gray-900">AI Assistant</h1>
              <p className="text-sm text-gray-600">Ask me about your clients, emails, or schedule meetings</p>
            </div>
            <div className="flex items-center space-x-3">
              <HubSpotIntegration />
            </div>
          </div>
        </div>

        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isLoadingSession ? (
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
                  
                  {/* Show tool results debug info for assistant messages */}
                  {message.role === 'assistant' && (
                    <ToolResultsDebug 
                      toolResults={message.tool_results || []} 
                    />
                  )}
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
              placeholder={currentSessionId ? "Type your message..." : "Create a session to start chatting..."}
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              disabled={isLoading || !currentSessionId}
            />
            <button
              type="submit"
              disabled={isLoading || !inputMessage.trim() || !currentSessionId}
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