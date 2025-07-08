import openai
from typing import List, Dict, Any, Optional
import structlog
from config import get_settings

logger = structlog.get_logger()

class OpenAIService:
    def __init__(self):
        self.client = None
        self.embedding_model = None
        self.chat_model = "gpt-4"
        self._initialized = False
    
    def _ensure_initialized(self):
        """Lazy initialization of OpenAI client"""
        if not self._initialized:
            settings = get_settings()
            if not settings.openai_api_key:
                logger.warning("OpenAI API key not configured")
                return False
            
            try:
                self.client = openai.OpenAI(api_key=settings.openai_api_key)
                self.embedding_model = settings.embedding_model
                self._initialized = True
                logger.info("OpenAI service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI service: {str(e)}")
                return False
        
        return self._initialized
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text using OpenAI embeddings API"""
        try:
            if not self._ensure_initialized():
                logger.error("OpenAI service not initialized")
                return []
            
            if not text or not text.strip():
                logger.warning("Empty text provided for embedding generation")
                return []
            
            # Clean and truncate text if needed
            clean_text = text.strip()[:8000]  # OpenAI has token limits
            
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=clean_text
            )
            
            embedding = response.data[0].embedding
            logger.info(f"Generated embedding for text (length: {len(clean_text)})")
            return embedding
            
        except Exception as e:
            logger.error(f"Failed to generate embedding: {str(e)}")
            return []
    
    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        try:
            if not self._ensure_initialized():
                logger.error("OpenAI service not initialized")
                return []
            
            if not texts:
                return []
            
            # Clean and prepare texts
            clean_texts = [text.strip()[:8000] for text in texts if text and text.strip()]
            
            if not clean_texts:
                return []
            
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=clean_texts
            )
            
            embeddings = [data.embedding for data in response.data]
            logger.info(f"Generated {len(embeddings)} embeddings in batch")
            return embeddings
            
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {str(e)}")
            return []
    
    async def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
        tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Generate chat completion with optional RAG context and function calling"""
        try:
            if not self._ensure_initialized():
                logger.error("OpenAI service not initialized")
                return {
                    "content": "I'm sorry, the AI service is not properly configured. Please check the OpenAI API key.",
                    "role": "assistant",
                    "tool_calls": None
                }
            
            # Build the messages array
            chat_messages = []
            
            # Add system prompt
            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})
            
            # Add context if provided (RAG)
            if context:
                context_message = f"""CONTEXT FROM USER'S ACTUAL DATA:
The following information is retrieved from the user's connected Gmail and HubSpot accounts. This is REAL data that you should use to answer their questions:

{context}

IMPORTANT: Use this context to provide accurate responses. When listing contacts, emails, or other data, use the information provided above. Do not say you don't have access to their data - you do have access through this context."""
                chat_messages.append({"role": "system", "content": context_message})
            
            # Add conversation messages
            chat_messages.extend(messages)
            
            # Prepare request parameters
            request_params = {
                "model": self.chat_model,
                "messages": chat_messages,
                "temperature": 0.7,
                "max_tokens": 1500
            }
            
            # Add tools if provided (function calling)
            if tools:
                request_params["tools"] = tools
                request_params["tool_choice"] = "auto"
            
            response = self.client.chat.completions.create(**request_params)
            
            message = response.choices[0].message
            
            result = {
                "content": message.content,
                "role": message.role,
                "tool_calls": None
            }
            
            # Handle function calls
            if hasattr(message, 'tool_calls') and message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": call.id,
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments
                        }
                    }
                    for call in message.tool_calls
                ]
            
            logger.info(f"Generated chat completion (tokens: {response.usage.total_tokens})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate chat completion: {str(e)}")
            return {
                "content": "I'm sorry, I encountered an error processing your request. Please try again.",
                "role": "assistant",
                "tool_calls": None
            }

    async def execute_proactive_workflow(
        self,
        user_request: str,
        context: Optional[str] = None,
        tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Execute a proactive workflow with enhanced AI capabilities"""
        try:
            # Enhanced system prompt for proactive actions
            system_prompt = """You are a highly capable AI assistant that can take proactive actions to help users. You have access to tools for:

1. **Contact Management**: Search contacts, get contact details
2. **Email Communication**: Send emails with professional templates
3. **Calendar Management**: Check availability, create events, suggest meeting times
4. **HubSpot Integration**: Add notes, update contact records
5. **Communication History**: Search past emails and interactions

When the user asks you to perform an action like "Schedule an appointment with Sara Smith", you should:

1. **Search for the contact** using search_contacts
2. **Check calendar availability** if scheduling is involved
3. **Send professional emails** with clear, concise messaging
4. **Create calendar events** when appointments are confirmed
5. **Add notes to HubSpot** to track interactions
6. **Handle edge cases gracefully** - if a contact isn't found, ask for clarification

**Key principles:**
- Always be proactive and take initiative
- Use professional, friendly communication
- Handle ambiguity by asking clarifying questions
- Provide multiple options when appropriate
- Keep the user informed of progress
- Be thorough but efficient in your approach

For appointment scheduling specifically:
- Search for the contact first
- Get their contact details including email
- Generate 3-5 available time slots
- Send a professional email with available times
- Be prepared to handle responses and reschedule if needed

Always use the available tools to accomplish tasks rather than just describing what you would do."""

            # Prepare messages for the workflow
            messages = [
                {
                    "role": "user",
                    "content": user_request
                }
            ]
            
            # Execute the chat completion with tools
            result = await self.chat_completion(
                messages=messages,
                system_prompt=system_prompt,
                context=context,
                tools=tools
            )
            
            # Enhanced result for workflow tracking
            return {
                **result,
                "workflow_type": "proactive",
                "original_request": user_request,
                "requires_tools": bool(result.get("tool_calls")),
                "next_action": "execute_tools" if result.get("tool_calls") else "complete"
            }
            
        except Exception as e:
            logger.error(f"Failed to execute proactive workflow: {str(e)}")
            return {
                "content": "I'm sorry, I encountered an error while trying to help you. Please try again.",
                "role": "assistant",
                "tool_calls": None,
                "error": str(e)
            }

    async def continue_workflow(
        self,
        conversation_history: List[Dict[str, str]],
        tool_results: List[Dict[str, Any]],
        context: Optional[str] = None,
        tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Continue a workflow after tool execution"""
        try:
            # Build conversation with tool results
            messages = conversation_history.copy()
            
            # Add tool results as system messages
            for result in tool_results:
                if result.get("success"):
                    messages.append({
                        "role": "system",
                        "content": f"Tool execution result: {result.get('tool_name', 'unknown')} completed successfully. Result: {result.get('result', 'No details')}"
                    })
                else:
                    messages.append({
                        "role": "system", 
                        "content": f"Tool execution failed: {result.get('tool_name', 'unknown')} - Error: {result.get('error', 'Unknown error')}"
                    })
            
            # Add follow-up prompt
            messages.append({
                "role": "system",
                "content": "Based on the tool execution results above, continue with the workflow. If all steps are complete, provide a summary. If additional actions are needed, use the appropriate tools."
            })
            
            # Continue with enhanced system prompt
            system_prompt = """You are continuing a proactive workflow. Review the tool execution results and:

1. **If successful**: Continue to the next logical step or provide completion summary
2. **If failed**: Try alternative approaches or ask for user guidance
3. **If partially complete**: Continue with remaining steps

Always keep the user informed of progress and next steps."""
            
            result = await self.chat_completion(
                messages=messages,
                system_prompt=system_prompt,
                context=context,
                tools=tools
            )
            
            return {
                **result,
                "workflow_status": "continued",
                "requires_tools": bool(result.get("tool_calls"))
            }
            
        except Exception as e:
            logger.error(f"Failed to continue workflow: {str(e)}")
            return {
                "content": "I encountered an error while continuing the workflow. Please try again.",
                "role": "assistant",
                "tool_calls": None,
                "error": str(e)
            }

# Global instance
openai_service = OpenAIService() 