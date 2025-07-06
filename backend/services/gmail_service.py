"""
Gmail API service for fetching and processing emails
"""
import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import structlog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re
from html import unescape
from bs4 import BeautifulSoup

logger = structlog.get_logger()

class GmailService:
    """Gmail API service for email operations"""
    
    def __init__(self):
        self.service = None
        self.credentials = None
    
    def initialize_service(self, access_token: str, refresh_token: str) -> bool:
        """Initialize Gmail service with OAuth credentials"""
        try:
            # Create credentials object
            self.credentials = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.getenv("GOOGLE_CLIENT_ID"),
                client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                scopes=[
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify",
                    "https://www.googleapis.com/auth/gmail.compose"
                ]
            )
            
            # Refresh token if needed
            if self.credentials.expired:
                self.credentials.refresh(Request())
            
            # Build Gmail service
            self.service = build('gmail', 'v1', credentials=self.credentials)
            
            logger.info("Gmail service initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Gmail service: {str(e)}")
            return False
    
    async def list_messages(self, days_back: int = 30, max_results: int = 100) -> List[Dict[str, Any]]:
        """List recent messages from Gmail"""
        try:
            if not self.service:
                raise Exception("Gmail service not initialized")
            
            # Calculate date for filtering
            since_date = datetime.now() - timedelta(days=days_back)
            query = f"after:{since_date.strftime('%Y/%m/%d')}"
            
            # Get message list
            result = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = result.get('messages', [])
            logger.info(f"Retrieved {len(messages)} messages from Gmail")
            
            return messages
            
        except HttpError as e:
            logger.error(f"Gmail API error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to list Gmail messages: {str(e)}")
            raise
    
    async def get_message_content(self, message_id: str) -> Dict[str, Any]:
        """Get full message content including headers and body"""
        try:
            if not self.service:
                raise Exception("Gmail service not initialized")
            
            # Get message details
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Extract message data
            headers = message['payload'].get('headers', [])
            
            # Parse headers
            subject = self._get_header_value(headers, 'Subject') or "No Subject"
            sender = self._get_header_value(headers, 'From') or "Unknown Sender"
            recipient = self._get_header_value(headers, 'To') or "Unknown Recipient"
            date_str = self._get_header_value(headers, 'Date') or ""
            
            # Parse date
            received_at = self._parse_email_date(date_str)
            
            # Extract body content
            body_text = self._extract_body_text(message['payload'])
            
            # Get thread ID and labels
            thread_id = message.get('threadId', '')
            labels = message.get('labelIds', [])
            
            # Check if message is read
            is_read = 'UNREAD' not in labels
            
            return {
                'gmail_id': message_id,
                'subject': subject,
                'sender': sender,
                'recipient': recipient,
                'content': body_text,
                'received_at': received_at,
                'thread_id': thread_id,
                'labels': labels,
                'is_read': is_read
            }
            
        except HttpError as e:
            logger.error(f"Gmail API error getting message {message_id}: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to get message content for {message_id}: {str(e)}")
            raise
    
    async def search_messages(self, query: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """Search messages with Gmail search syntax"""
        try:
            if not self.service:
                raise Exception("Gmail service not initialized")
            
            # Search for messages
            result = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = result.get('messages', [])
            logger.info(f"Found {len(messages)} messages for query: {query}")
            
            return messages
            
        except HttpError as e:
            logger.error(f"Gmail API error searching: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to search Gmail messages: {str(e)}")
            raise
    
    async def send_email(self, to: str, subject: str, body: str, cc: Optional[str] = None) -> Dict[str, Any]:
        """Send an email via Gmail API"""
        try:
            if not self.service:
                raise Exception("Gmail service not initialized")
            
            # Create message
            message = MIMEMultipart()
            message['to'] = to
            message['subject'] = subject
            
            if cc:
                message['cc'] = cc
            
            # Add body
            message.attach(MIMEText(body, 'plain'))
            
            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            
            # Send message
            result = self.service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()
            
            logger.info(f"Email sent successfully: {result.get('id')}")
            return result
            
        except HttpError as e:
            logger.error(f"Gmail API error sending email: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            raise
    
    def _get_header_value(self, headers: List[Dict], name: str) -> Optional[str]:
        """Extract header value by name"""
        for header in headers:
            if header['name'].lower() == name.lower():
                return header['value']
        return None
    
    def _parse_email_date(self, date_str: str) -> datetime:
        """Parse email date string to datetime"""
        try:
            # Try different date formats
            formats = [
                '%a, %d %b %Y %H:%M:%S %z',
                '%a, %d %b %Y %H:%M:%S %Z',
                '%d %b %Y %H:%M:%S %z',
                '%d %b %Y %H:%M:%S %Z',
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
            
            # If all formats fail, return current time
            logger.warning(f"Could not parse date: {date_str}")
            return datetime.now()
            
        except Exception as e:
            logger.error(f"Error parsing email date: {str(e)}")
            return datetime.now()
    
    def _extract_body_text(self, payload: Dict) -> str:
        """Extract readable text from email payload"""
        try:
            body = ""
            
            # Handle multipart messages
            if 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain':
                        data = part['body'].get('data', '')
                        if data:
                            body += base64.urlsafe_b64decode(data).decode('utf-8')
                    elif part['mimeType'] == 'text/html':
                        data = part['body'].get('data', '')
                        if data:
                            html_content = base64.urlsafe_b64decode(data).decode('utf-8')
                            body += self._html_to_text(html_content)
            
            # Handle single part messages
            elif payload['mimeType'] == 'text/plain':
                data = payload['body'].get('data', '')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8')
            
            elif payload['mimeType'] == 'text/html':
                data = payload['body'].get('data', '')
                if data:
                    html_content = base64.urlsafe_b64decode(data).decode('utf-8')
                    body = self._html_to_text(html_content)
            
            # Clean up the text
            body = self._clean_email_text(body)
            
            return body
            
        except Exception as e:
            logger.error(f"Error extracting email body: {str(e)}")
            return ""
    
    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML to plain text"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            return soup.get_text()
        except Exception as e:
            logger.error(f"Error converting HTML to text: {str(e)}")
            return html_content
    
    def _clean_email_text(self, text: str) -> str:
        """Clean email text for better processing"""
        try:
            # Remove excessive whitespace
            text = re.sub(r'\s+', ' ', text)
            
            # Remove HTML entities
            text = unescape(text)
            
            # Remove email signatures (basic patterns)
            text = re.sub(r'\n--\s*\n.*', '', text, flags=re.DOTALL)
            text = re.sub(r'\nSent from.*', '', text, flags=re.DOTALL)
            
            # Remove forwarded/replied headers
            text = re.sub(r'\n>.*', '', text, flags=re.MULTILINE)
            text = re.sub(r'\nFrom:.*\nTo:.*\nSent:.*', '', text, flags=re.DOTALL)
            
            return text.strip()
            
        except Exception as e:
            logger.error(f"Error cleaning email text: {str(e)}")
            return text

# Global service instance
gmail_service = GmailService() 