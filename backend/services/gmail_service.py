"""
Gmail API service for fetching and processing emails
"""
import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone
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
        self.user_id = None  # Track user ID for token updates
        self.token_update_callback = None  # Callback to update tokens in database
    
    def initialize_service(self, access_token: str, refresh_token: str, user_id: str = None, token_update_callback = None) -> bool:
        """Initialize Gmail service with OAuth credentials"""
        try:
            # Store user context for token updates
            self.user_id = user_id
            self.token_update_callback = token_update_callback
            
            # Check if refresh token is missing
            if not refresh_token or refresh_token.strip() == "":
                logger.warning(f"Google refresh token is missing for user {user_id} - service will have limited functionality")
                # Don't fail completely, but log the issue
                # We can still attempt to use the access token if it's valid
                
            # Create credentials object
            self.credentials = Credentials(
                token=access_token,
                refresh_token=refresh_token if refresh_token and refresh_token.strip() else None,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.getenv("GOOGLE_CLIENT_ID"),
                client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                scopes=[
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify",
                    "https://www.googleapis.com/auth/gmail.compose",
                    "https://www.googleapis.com/auth/calendar"
                ]
            )
            
            # Check if token needs refresh (if expired or expiring soon)
            needs_refresh = self.credentials.expired
            if not needs_refresh and self.credentials.expiry:
                # Refresh if token expires within 10 minutes
                from datetime import datetime, timezone, timedelta
                ten_minutes_from_now = datetime.now(timezone.utc) + timedelta(minutes=10)
                needs_refresh = self.credentials.expiry <= ten_minutes_from_now
            
            # Try to refresh token if needed and we have a refresh token
            if needs_refresh and refresh_token and refresh_token.strip():
                try:
                    logger.info(f"Google token needs refresh for user {user_id}, attempting refresh...")
                    old_token = self.credentials.token
                    self.credentials.refresh(Request())
                    logger.info(f"Google token refreshed successfully for user {user_id}")
                    
                    # Save updated tokens to database if callback provided
                    if self.token_update_callback and self.credentials.token != old_token:
                        try:
                            self.token_update_callback(
                                user_id,
                                self.credentials.token,
                                self.credentials.refresh_token,
                                self.credentials.expiry
                            )
                            logger.info(f"Updated tokens saved to database for user {user_id}")
                        except Exception as save_error:
                            logger.error(f"Failed to save updated tokens for user {user_id}: {str(save_error)}")
                    
                except Exception as refresh_error:
                    logger.error(f"Failed to refresh Google token for user {user_id}: {str(refresh_error)}")
                    # Don't fail completely - the access token might still be valid
                    logger.warning(f"Continuing with existing access token for user {user_id} despite refresh failure")
            elif needs_refresh and not refresh_token:
                logger.error(f"Google token is expired for user {user_id} and no refresh token available - user needs to reauthenticate")
                return False
            
            # Build Gmail and Calendar services
            try:
                self.service = build('gmail', 'v1', credentials=self.credentials)
                self.calendar_service = build('calendar', 'v3', credentials=self.credentials)
                
                # Test the service with a simple call
                profile = self.service.users().getProfile(userId='me').execute()
                logger.info(f"Gmail service initialized successfully for user {user_id}: {profile.get('emailAddress', 'unknown')}")
                return True
                
            except Exception as service_error:
                logger.error(f"Failed to build Gmail/Calendar services for user {user_id}: {str(service_error)}")
                return False
            
        except Exception as e:
            logger.error(f"Failed to initialize Gmail service for user {user_id}: {str(e)}")
            return False
    
    async def list_messages(self, days_back: int = 30, max_results: int = 500) -> List[Dict[str, Any]]:
        """List recent messages from Gmail"""
        try:
            if not self.service:
                raise Exception("Gmail service not initialized")
            
            # Calculate date for filtering - use UTC timezone
            since_date = datetime.now(timezone.utc) - timedelta(days=days_back)
            
            # Use more precise query to get latest emails first
            # Use 'newer_than' for more precise time-based filtering
            query = f"newer_than:{days_back}d"
            
            logger.info(f"Querying Gmail with: {query}, max_results: {max_results}")
            
            # Get message list with pagination to ensure we get all recent emails
            all_messages = []
            page_token = None
            
            while len(all_messages) < max_results:
                # Get messages in batches
                batch_size = min(100, max_results - len(all_messages))
                
                request_params = {
                    'userId': 'me',
                    'q': query,
                    'maxResults': batch_size
                }
                
                if page_token:
                    request_params['pageToken'] = page_token
                
                result = self.service.users().messages().list(**request_params).execute()
                
                messages = result.get('messages', [])
                all_messages.extend(messages)
                
                # Check if there are more pages
                page_token = result.get('nextPageToken')
                if not page_token or not messages:
                    break
            
            # Sort by most recent first (Gmail should already do this, but let's be sure)
            logger.info(f"Retrieved {len(all_messages)} messages from Gmail")
            
            return all_messages
            
        except HttpError as e:
            logger.error(f"Gmail API error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to list Gmail messages: {str(e)}")
            raise
    
    async def list_latest_messages(self, max_results: int = 200) -> List[Dict[str, Any]]:
        """List the most recent messages without date filtering"""
        try:
            if not self.service:
                raise Exception("Gmail service not initialized")
            
            logger.info(f"Fetching latest {max_results} messages from Gmail (no date filter)")
            
            # Get message list without any date filtering to ensure we get the absolute latest
            all_messages = []
            page_token = None
            
            while len(all_messages) < max_results:
                # Get messages in batches
                batch_size = min(100, max_results - len(all_messages))
                
                request_params = {
                    'userId': 'me',
                    'maxResults': batch_size
                }
                
                if page_token:
                    request_params['pageToken'] = page_token
                
                result = self.service.users().messages().list(**request_params).execute()
                
                messages = result.get('messages', [])
                all_messages.extend(messages)
                
                # Check if there are more pages
                page_token = result.get('nextPageToken')
                if not page_token or not messages:
                    break
            
            logger.info(f"Retrieved {len(all_messages)} latest messages from Gmail")
            
            return all_messages
            
        except HttpError as e:
            logger.error(f"Gmail API error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to list latest Gmail messages: {str(e)}")
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
    
    async def create_calendar_event(
        self, 
        title: str, 
        start_datetime: str, 
        end_datetime: str,
        description: str = "",
        attendees: List[str] = None,
        location: str = ""
    ) -> Dict[str, Any]:
        """Create a calendar event in Google Calendar"""
        try:
            if not self.calendar_service:
                raise Exception("Calendar service not initialized")
            
            # Prepare event data
            event = {
                'summary': title,
                'location': location,
                'description': description,
                'start': {
                    'dateTime': start_datetime,
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': end_datetime,
                    'timeZone': 'UTC',
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},
                        {'method': 'popup', 'minutes': 10},
                    ],
                },
            }
            
            # Add attendees if provided
            if attendees:
                event['attendees'] = [{'email': email} for email in attendees]
            
            # Create the event
            result = self.calendar_service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            
            logger.info(f"Calendar event created successfully: {result.get('id')}")
            
            return {
                'id': result.get('id'),
                'htmlLink': result.get('htmlLink'),
                'summary': result.get('summary'),
                'start': result.get('start'),
                'end': result.get('end'),
                'attendees': result.get('attendees', []),
                'location': result.get('location', ''),
                'status': result.get('status')
            }
            
        except Exception as e:
            logger.error(f"Failed to create calendar event: {str(e)}")
            raise e

    async def list_calendar_events(
        self, 
        days_forward: int = 30,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """List upcoming calendar events from Google Calendar"""
        try:
            if not self.calendar_service:
                raise Exception("Calendar service not initialized")
            
            # Calculate time range
            now = datetime.now(timezone.utc)
            end_time = now + timedelta(days=days_forward)
            
            # Format times for Google Calendar API
            time_min = now.isoformat()
            time_max = end_time.isoformat()
            
            logger.info(f"Fetching calendar events from {time_min} to {time_max}")
            
            # Get events from primary calendar
            result = self.calendar_service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = result.get('items', [])
            logger.info(f"Retrieved {len(events)} calendar events")
            
            # Process events
            processed_events = []
            for event in events:
                # Handle different event types (all-day vs timed)
                start = event.get('start', {})
                end = event.get('end', {})
                
                # Check if it's an all-day event
                is_all_day = 'date' in start
                
                if is_all_day:
                    start_datetime = None
                    end_datetime = None
                    start_date = start.get('date')
                    end_date = end.get('date')
                else:
                    start_datetime_str = start.get('dateTime')
                    end_datetime_str = end.get('dateTime')
                    
                    # Parse datetime strings
                    start_datetime = datetime.fromisoformat(start_datetime_str.replace('Z', '+00:00')) if start_datetime_str else None
                    end_datetime = datetime.fromisoformat(end_datetime_str.replace('Z', '+00:00')) if end_datetime_str else None
                    start_date = None
                    end_date = None
                
                # Extract organizer info
                organizer = event.get('organizer', {})
                organizer_email = organizer.get('email', '')
                organizer_name = organizer.get('displayName', organizer_email)
                
                # Extract attendees
                attendees_list = event.get('attendees', [])
                attendees_data = [
                    {
                        'email': attendee.get('email', ''),
                        'displayName': attendee.get('displayName', ''),
                        'responseStatus': attendee.get('responseStatus', 'needsAction')
                    }
                    for attendee in attendees_list
                ]
                
                processed_event = {
                    'google_event_id': event.get('id'),
                    'title': event.get('summary', 'No Title'),
                    'description': event.get('description', ''),
                    'location': event.get('location', ''),
                    'start_datetime': start_datetime,
                    'end_datetime': end_datetime,
                    'start_date': start_date,
                    'end_date': end_date,
                    'is_all_day': is_all_day,
                    'status': event.get('status', 'confirmed'),
                    'organizer_email': organizer_email,
                    'organizer_name': organizer_name,
                    'attendees': attendees_data,
                    'html_link': event.get('htmlLink', ''),
                    'created': event.get('created'),
                    'updated': event.get('updated')
                }
                
                processed_events.append(processed_event)
            
            return processed_events
            
        except Exception as e:
            logger.error(f"Failed to list calendar events: {str(e)}")
            raise e

# Global service instance
gmail_service = GmailService() 