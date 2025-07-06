export interface User {
  id: string;
  email: string;
  name?: string;
  google_id?: string;
  hubspot_id?: string;
  created_at: string;
  updated_at: string;
}

export interface AuthStatus {
  user: {
    id: string;
    email: string;
    name?: string;
  };
  integrations: {
    google: boolean;
    hubspot: boolean;
  };
}

export interface Token {
  access_token: string;
  token_type: string;
}

export interface ChatMessage {
  message: string;
  context?: string;
}

export interface ChatResponse {
  response: string;
  context_used?: string;
  sources?: Array<{
    id: string;
    content: string;
    source_type: string;
    metadata?: Record<string, any>;
  }>;
  tool_results?: ToolResult[];
}

export interface ToolResult {
  tool: string;
  status: 'success' | 'error';
  result?: any;
  error?: string;
}

export interface ConversationHistory {
  id: string;
  message: string;
  response: string;
  created_at: string;
}

export interface OngoingInstruction {
  id: string;
  instruction: string;
  is_active: boolean;
  created_at: string;
}

export interface Email {
  id: string;
  subject?: string;
  sender?: string;
  recipient?: string;
  date?: string;
  is_read: boolean;
  is_sent: boolean;
}

export interface Contact {
  id: string;
  name?: string;
  email?: string;
  phone?: string;
  company?: string;
  notes?: string;
}

export interface SyncStatus {
  service: string;
  status: string;
  last_sync?: string;
  total_items: number;
  error_message?: string;
}

export interface IntegrationSummary {
  gmail: {
    total_emails: number;
    unread_emails: number;
    last_sync?: string;
  };
  hubspot: {
    total_contacts: number;
    last_sync?: string;
  };
}

export interface ApiResponse<T> {
  data?: T;
  error?: string;
  message?: string;
}

export interface ApiError {
  detail: string;
  status_code: number;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface GoogleAuthResponse {
  access_token: string;
  user: User;
}

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface CreateChatSessionRequest {
  title?: string;
}

export interface UpdateChatSessionRequest {
  title: string;
}

export interface IntegrationStatus {
  google: boolean;
  hubspot: boolean;
}

export interface HubSpotContact {
  id: string;
  firstName?: string;
  lastName?: string;
  email?: string;
  phone?: string;
  company?: string;
} 