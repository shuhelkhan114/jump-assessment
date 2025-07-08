# Thank You Email Feature

## Overview

This feature automatically sends thank you emails to new customers when they are added to your HubSpot contact list. The system works in two ways:

1. **Real-time**: When the Gmail polling service detects a new email sender and creates a HubSpot contact, it immediately sends a thank you email
2. **Batch processing**: Periodic polling checks for any contacts who haven't received thank you emails yet and sends them

## How It Works

### Real-Time Thank You Emails

1. **Gmail Monitoring**: The system continuously monitors your Gmail inbox for new emails
2. **Contact Detection**: When an email arrives from an unknown sender, the system:
   - Extracts the sender's email address
   - Checks if they already exist as a HubSpot contact
   - If not, creates a new HubSpot contact automatically
3. **Immediate Thank You**: As soon as the contact is created, the system sends a personalized thank you email
4. **Tracking**: The system marks the contact as having received a thank you email to prevent duplicates

### Batch Processing

1. **Periodic Checks**: Every 30 minutes, the system checks all HubSpot contacts
2. **Identifies New Contacts**: Finds contacts who haven't received thank you emails yet
3. **Sends Thank You Emails**: Sends personalized thank you emails to all new contacts
4. **Updates Records**: Marks contacts as having received thank you emails

## Email Content

- **Subject**: "Thank you for being a customer"
- **Body**: "Hello {Name}, Thank you for being a customer."

The system personalizes emails using the contact's first and last name from HubSpot. If no name is available, it uses the email username.

## Requirements

- **HubSpot Integration**: Active HubSpot OAuth connection to access contacts
- **Gmail Integration**: Active Gmail OAuth connection to send emails
- **Automatic Sync**: The auto-sync system must be running (handled by Celery)

## Technical Implementation

### Database Changes

The system adds two new fields to the `hubspot_contacts` table:
- `thank_you_email_sent` (Boolean): Whether a thank you email has been sent
- `thank_you_email_sent_at` (Timestamp): When the thank you email was sent

### Components

1. **Database Migration**: Automatically adds new fields on startup
2. **Gmail Polling Service**: Enhanced to send thank you emails when creating contacts
3. **Celery Task**: Background task for batch processing (`send_thank_you_emails_to_new_contacts`)
4. **Auto-Sync Integration**: Thank you emails are part of the regular sync process
5. **API Endpoint**: Manual trigger at `/integrations/hubspot/send-thank-you-emails`

### Error Handling

- **Missing Database Fields**: Gracefully handles cases where migration hasn't run yet
- **API Failures**: Logs errors and continues processing other contacts
- **Duplicate Prevention**: Prevents sending multiple thank you emails to the same contact
- **Service Unavailability**: Handles cases where Gmail or HubSpot services are temporarily unavailable

## Usage

### Automatic Operation

The feature works automatically once both integrations are connected:
1. Connect your Gmail account
2. Connect your HubSpot account
3. Thank you emails will be sent automatically as new contacts are created

### Manual Trigger

You can manually trigger thank you emails via the API:

```bash
POST /integrations/hubspot/send-thank-you-emails
Authorization: Bearer <your-token>
```

Response:
```json
{
  "success": true,
  "message": "Thank you email task started",
  "task_id": "task-id-here",
  "user_id": "user-id-here"
}
```

### Testing

Use the test script to verify functionality:

```bash
python3 backend/test_thank_you_emails.py
```

This will:
1. Check database schema
2. Test the Celery task
3. Test the contact creation flow

## Monitoring

### Logs

Monitor thank you email activity in the application logs:

```bash
docker-compose logs backend | grep "thank you\|Thank you"
```

### Database Queries

Check thank you email status:

```sql
-- Count contacts by thank you email status
SELECT 
    thank_you_email_sent,
    COUNT(*) as count
FROM hubspot_contacts 
GROUP BY thank_you_email_sent;

-- Recent thank you emails sent
SELECT 
    firstname, lastname, email, thank_you_email_sent_at
FROM hubspot_contacts 
WHERE thank_you_email_sent = true 
ORDER BY thank_you_email_sent_at DESC 
LIMIT 10;
```

## Configuration

### Email Template Customization

The email template is currently hardcoded but can be customized by modifying the `_send_thank_you_email` method in `backend/services/gmail_polling_service.py`:

```python
# Create email content
subject = "Thank you for being a customer"
body = f"Hello {contact_name}, Thank you for being a customer."
```

### Polling Frequency

The system polls for new contacts every 30 minutes as part of the auto-sync process. This can be adjusted in the Celery beat configuration.

### Rate Limiting

The system includes rate limiting to respect Gmail API quotas:
- 2-second delay between API calls
- Maximum 20 emails processed per polling cycle
- Exponential backoff on API errors

## Troubleshooting

### Common Issues

1. **No thank you emails sent**: 
   - Check that both Gmail and HubSpot integrations are connected
   - Verify the auto-sync system is running
   - Check logs for API errors

2. **Duplicate emails**: 
   - The system prevents duplicates automatically
   - Check the `thank_you_email_sent` field in the database

3. **Migration errors**:
   - The system handles missing database fields gracefully
   - Restart the application to trigger migrations

### Debug Mode

Enable debug logging to see detailed operation:

```python
# In backend/main.py, set debug=True for the database engine
```

## Future Enhancements

Potential improvements for the feature:

1. **Customizable Templates**: Allow users to customize email templates
2. **Delay Configuration**: Allow users to set delays before sending thank you emails
3. **Conditional Logic**: Send different emails based on contact properties
4. **Unsubscribe Handling**: Respect unsubscribe preferences
5. **Analytics**: Track open rates and engagement metrics 