"""
Tools service for defining and managing AI function calling tools
"""
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger()

class ToolsService:
    """Service for managing AI function calling tools"""
    
    def __init__(self):
        self.tools = self._define_tools()
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get all available tools for OpenAI function calling"""
        return self.tools
    
    def get_tool_names(self) -> List[str]:
        """Get list of all tool names"""
        return [tool["function"]["name"] for tool in self.tools]
    
    def _define_tools(self) -> List[Dict[str, Any]]:
        """Define OpenAI function schemas for available tools"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_contacts",
                    "description": "Search for contacts in HubSpot CRM by name, email, or company. Use this to find contact information before scheduling meetings.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (name, email, or company name)"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of contacts to return (default: 5)",
                                "default": 5
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "send_email",
                    "description": "Send an email to a recipient using Gmail. Use this when the user asks to send an email, compose a message, or reach out to someone.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {
                                "type": "string",
                                "description": "The email address of the recipient"
                            },
                            "subject": {
                                "type": "string",
                                "description": "The subject line of the email"
                            },
                            "body": {
                                "type": "string",
                                "description": "The body content of the email in plain text or HTML"
                            },
                            "cc": {
                                "type": "string",
                                "description": "Optional CC email address",
                                "default": None
                            }
                        },
                        "required": ["to", "subject", "body"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_calendar_event",
                    "description": "Create a calendar event in Google Calendar. Use this when the user wants to schedule a meeting, appointment, or event. IMPORTANT: When scheduling with other people, first use search_contacts to find their email address, then include their email in attendees.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "The title/summary of the calendar event"
                            },
                            "description": {
                                "type": "string",
                                "description": "Description or details about the event"
                            },
                            "start_datetime": {
                                "type": "string",
                                "description": "Start date and time in ISO format (e.g., '2024-07-08T10:00:00Z')"
                            },
                            "end_datetime": {
                                "type": "string",
                                "description": "End date and time in ISO format (e.g., '2024-07-08T11:00:00Z')"
                            },
                            "attendees": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                },
                                "description": "List of attendee email addresses - REQUIRED when scheduling meetings with other people"
                            },
                            "location": {
                                "type": "string",
                                "description": "Location of the event (optional)",
                                "default": ""
                            }
                        },
                        "required": ["title", "start_datetime", "end_datetime", "attendees"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_calendar_schedule",
                    "description": "Get the user's calendar schedule and upcoming events. Use this when the user asks about their schedule, calendar, appointments, or what they have planned.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days_forward": {
                                "type": "integer",
                                "description": "Number of days forward to look for events (default: 7)",
                                "default": 7
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of events to return (default: 20)",
                                "default": 20
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_hubspot_contact",
                    "description": "Create a new contact in HubSpot CRM. Use this when the user wants to add a new person to their contacts or CRM.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "email": {
                                "type": "string",
                                "description": "The email address of the contact"
                            },
                            "firstname": {
                                "type": "string",
                                "description": "First name of the contact"
                            },
                            "lastname": {
                                "type": "string",
                                "description": "Last name of the contact"
                            },
                            "company": {
                                "type": "string",
                                "description": "Company name where the contact works",
                                "default": ""
                            },
                            "jobtitle": {
                                "type": "string",
                                "description": "Job title of the contact",
                                "default": ""
                            },
                            "phone": {
                                "type": "string",
                                "description": "Phone number of the contact",
                                "default": ""
                            },
                            "notes": {
                                "type": "string",
                                "description": "Additional notes about the contact",
                                "default": ""
                            }
                        },
                        "required": ["email", "firstname", "lastname"]
                    }
                }
            }
        ]

# Global instance
tools_service = ToolsService() 