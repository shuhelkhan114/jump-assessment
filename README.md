# Financial Agent - AI Assistant for Financial Advisors

A comprehensive AI agent that integrates with Gmail, Google Calendar, and HubSpot to provide intelligent assistance for financial advisors.

## Features

- **Google OAuth Integration**: Secure authentication with Gmail and Calendar access
- **HubSpot CRM Integration**: Connect and sync with HubSpot contacts and notes
- **AI-Powered Chat Interface**: ChatGPT-like interface for querying client information
- **RAG (Retrieval-Augmented Generation)**: Uses pgvector for semantic search through emails and CRM data
- **Tool Calling**: AI can perform actions like scheduling meetings, sending emails, creating contacts
- **Ongoing Instructions**: Set persistent instructions for proactive behavior
- **Memory System**: Maintains context and task continuity

## Tech Stack

### Backend
- **FastAPI** - Modern, fast web framework for building APIs
- **PostgreSQL with pgvector** - Vector database for RAG functionality
- **Redis** - Caching and message broker for background tasks
- **Celery** - Distributed task queue for background processing
- **OpenAI GPT-4** - LLM for chat and tool calling
- **OAuth 2.0** - Google and HubSpot authentication

### Frontend
- **React with TypeScript** - Type-safe user interface framework
- **Tailwind CSS** - Utility-first CSS framework
- **React Query** - Data fetching and caching
- **React Router** - Client-side routing

### Infrastructure
- **Docker** - Containerization
- **Docker Compose** - Multi-container orchestration

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Google OAuth credentials
- HubSpot OAuth credentials
- OpenAI API key

### 1. Clone the Repository
```bash
git clone <repository-url>
cd financial-agent
```

### 2. Set Up Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:

```env
# Database
DATABASE_URL=postgresql://postgres:password@db:5432/financial_agent

# Authentication
SECRET_KEY=your-secret-key-here
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
HUBSPOT_CLIENT_ID=your-hubspot-client-id
HUBSPOT_CLIENT_SECRET=your-hubspot-client-secret

# OpenAI
OPENAI_API_KEY=your-openai-api-key
```

### 3. OAuth Setup

#### Google OAuth
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Gmail API and Calendar API
4. Create OAuth 2.0 credentials
5. Add `http://localhost:8000/auth/google/callback` to authorized redirect URIs
6. Add `webshookeng@gmail.com` as a test user

#### HubSpot OAuth
1. Go to [HubSpot Developer Portal](https://developers.hubspot.com/)
2. Create a new app
3. Configure OAuth settings
4. Add `http://localhost:8000/auth/hubspot/callback` to redirect URIs

### 4. Run the Application
```bash
# Build and start all services
docker-compose up --build

# The application will be available at:
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Documentation: http://localhost:8000/docs
# Redis: localhost:6379
# PostgreSQL: localhost:5432
```

### 5. Initialize the Database
The database will be automatically initialized with the pgvector extension and required tables.

## Development

### Backend Development
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend Development
```bash
cd frontend
npm install
npm start
```

## Usage

### 1. Authentication
- Visit `http://localhost:3000`
- Click "Login with Google" to authenticate
- Connect your HubSpot account from the integrations page

### 2. Sync Data
- Go to Integrations page
- Click "Sync Gmail" to import emails
- Click "Sync HubSpot" to import contacts

### 3. Chat with AI
- Use the chat interface to ask questions about your clients
- Examples:
  - "Who mentioned their kid plays baseball?"
  - "What did Sarah say about her retirement plans?"
  - "Schedule a meeting with John Smith"

### 4. Set Ongoing Instructions
- Add persistent instructions for proactive behavior
- Examples:
  - "When someone emails who isn't in HubSpot, create a contact"
  - "When I create a calendar event, email the attendees"

## API Endpoints

### Authentication
- `GET /auth/google/login` - Initiate Google OAuth
- `GET /auth/google/callback` - Handle Google OAuth callback
- `GET /auth/hubspot/login` - Initiate HubSpot OAuth
- `GET /auth/status` - Get authentication status

### Chat
- `POST /chat/message` - Send message to AI
- `GET /chat/history` - Get conversation history
- `POST /chat/instructions` - Add ongoing instruction

### Integrations
- `POST /integrations/gmail/sync` - Sync Gmail data
- `POST /integrations/hubspot/sync` - Sync HubSpot data
- `GET /integrations/sync-status` - Get sync status

## Architecture

### RAG System
- Uses OpenAI embeddings to vectorize emails and CRM data
- Stores vectors in PostgreSQL with pgvector extension
- Performs semantic search for relevant context
- Exact search for maximum accuracy in MVP

### Tool Calling
- AI can execute actions through defined tools
- Tools include: send email, create calendar event, create contact
- Task persistence for multi-step workflows

### Memory System
- Stores ongoing instructions in database
- Maintains conversation context
- Enables proactive behavior based on triggers

## Deployment

### Production Environment Variables
```env
DATABASE_URL=postgresql://user:password@host:5432/database
SECRET_KEY=production-secret-key
GOOGLE_CLIENT_ID=production-google-client-id
GOOGLE_CLIENT_SECRET=production-google-client-secret
HUBSPOT_CLIENT_ID=production-hubspot-client-id
HUBSPOT_CLIENT_SECRET=production-hubspot-client-secret
OPENAI_API_KEY=production-openai-api-key
```

### Deployment Options
- **Railway**: Supports PostgreSQL with pgvector
- **Render**: Managed PostgreSQL with pgvector
- **AWS/GCP**: Use managed PostgreSQL services
- **Docker**: Can be deployed anywhere with Docker support

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For questions or issues, please open an issue on GitHub or contact the development team. 