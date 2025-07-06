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
                context_message = f"Here's relevant context to help answer the user's question:\n\n{context}\n\nPlease use this context to provide accurate and helpful responses."
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

# Global instance
openai_service = OpenAIService() 