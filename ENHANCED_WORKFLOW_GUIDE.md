# Enhanced Appointment Scheduling Workflow

## Overview

The appointment scheduling workflow has been enhanced to properly handle the scenario where a user asks to schedule a call without specifying a time. The system now:

1. **Checks your 24-hour availability** instead of directly sending emails
2. **Shares available time slots** with contacts
3. **Handles time selection and conflict resolution** through back-and-forth negotiation
4. **Schedules the meeting** only when a mutually available time is confirmed

## Enhanced Workflow Steps

### Step 1: Contact Search
- Searches for the contact in HubSpot and email history
- Uses confidence scoring to find the best match
- Stores contact details for subsequent steps

### Step 2: Contact Selection (AI Decision)
- AI evaluates search results and selects the best matching contact
- If no good match found, asks user for clarification
- Stores selected contact's email for next steps

### Step 3: Generate 24-Hour Availability ⭐ **NEW**
- **Enhancement**: Now generates availability for next 24 hours automatically
- Checks calendar for conflicts across multiple days
- Generates 6 available time slots within business hours (9 AM - 5 PM)
- Formats times nicely (e.g., "Monday, December 16 at 2:00 PM")

### Step 4: Send Availability Email ⭐ **ENHANCED**
- **Enhancement**: Sends professional email with available time slots
- Email includes:
  - Explanation of wanting to schedule a call
  - Clear list of available time slots
  - Request for them to reply with preferred time
  - Friendly and professional tone

### Step 5: Wait for Response
- Waits up to 72 hours for email response
- Monitors for time selection, decline, or reschedule requests

### Step 6: Process Time Selection ⭐ **NEW**
- **Enhancement**: Intelligently processes their response
- Extracts selected time from email reply
- Checks calendar availability for that exact time slot
- **If available**: Creates calendar event and sends confirmation
- **If occupied**: Sends polite conflict email with alternative times

### Step 7: Handle Conflicts and Negotiate ⭐ **NEW**
- **Enhancement**: Continues negotiation if conflicts occur
- Offers alternative times from your availability
- Repeats conflict resolution until suitable time found
- Gracefully handles multiple back-and-forth exchanges

### Step 8: Finalize and Log
- Creates calendar event with confirmed time
- Adds interaction note to HubSpot with appointment details
- Sends final confirmation email with calendar invite

## Key Improvements

### ✅ Availability-First Approach
- **Before**: Directly sent appointment emails
- **After**: First checks and shares your availability

### ✅ Smart Time Negotiation
- **Before**: Simple accept/decline handling
- **After**: Intelligent conflict resolution with alternatives

### ✅ 24-Hour Availability Window
- **Before**: Required specific date input
- **After**: Automatically generates next 24 hours of availability

### ✅ Professional Email Templates
- **Before**: Generic appointment requests
- **After**: Clear, structured emails with time options

### ✅ Conflict Resolution Loop
- **Before**: Failed if time was occupied
- **After**: Continues negotiating until mutual time found

## Example Workflow

**User Request**: "Schedule a call with Sara Smith"

**System Response**:

1. 🔍 Searches for "Sara Smith" in contacts
2. ✅ Finds Sara Smith (sara.smith@example.com) 
3. 📅 Generates your next 24-hour availability:
   - Monday, Dec 16 at 10:00 AM
   - Monday, Dec 16 at 2:30 PM
   - Tuesday, Dec 17 at 9:30 AM
   - Tuesday, Dec 17 at 11:00 AM
   - Tuesday, Dec 17 at 3:00 PM
   - Tuesday, Dec 17 at 4:30 PM

4. 📧 Sends email to Sara:
   ```
   Subject: Let's Schedule Our Call

   Hi Sara,

   I'd like to schedule a call with you. I have the following time slots 
   available over the next 24 hours:

   • Monday, December 16 at 10:00 AM
   • Monday, December 16 at 2:30 PM  
   • Tuesday, December 17 at 9:30 AM
   • Tuesday, December 17 at 11:00 AM
   • Tuesday, December 17 at 3:00 PM
   • Tuesday, December 17 at 4:30 PM

   Please reply with your preferred time and I'll send you a calendar invite.

   Best regards
   ```

5. ⏳ Waits for Sara's response

6. 📨 Sara replies: "Tuesday at 11:00 AM works great!"

7. 🔍 Checks calendar for Tuesday, Dec 17 at 11:00 AM
   - **If available**: Creates event, sends confirmation
   - **If occupied**: Sends alternatives

8. ✅ Creates calendar event and HubSpot note

## Technical Implementation

### Enhanced Tools
- **`get_time_suggestions`**: New `next_24_hours` parameter
- **`AI Decision Steps`**: Intelligent email composition and conflict resolution
- **`Workflow Engine`**: 8-step process with state management

### API Endpoints
- `POST /api/proactive/schedule-appointment`: Start enhanced workflow
- `GET /api/proactive/workflow/{id}`: Check workflow status
- `POST /api/proactive/continue-workflow`: Handle email responses

### Database Persistence
- Full workflow state tracking
- Step-by-step execution history
- Response handling and continuation

## Testing

Run the test script to verify the enhanced workflow:

```bash
python test_appointment_workflow.py
```

This will verify:
- ✅ Proper 24-hour availability generation
- ✅ Professional email composition with time slots
- ✅ Workflow state persistence
- ✅ Multi-step execution without breaking existing functionality

## Benefits

1. **Better User Experience**: No more manual time coordination
2. **Professional Communication**: Clear, structured emails
3. **Conflict Resolution**: Automatic negotiation until agreement
4. **Time Efficiency**: Shares multiple options upfront
5. **Calendar Integration**: Seamless event creation when confirmed
6. **HubSpot Tracking**: Complete interaction history

The enhanced workflow now properly addresses your requirement: when you ask to schedule a call without mentioning time, it shares your availability and handles the entire negotiation process until a mutually suitable time is confirmed. 