# 🧪 Financial Agent MVP - Testing Guide

## **✅ System Status**
- **Backend**: ✅ Running (http://localhost:8000)
- **Frontend**: ✅ Running (http://localhost:3000)
- **Database**: ✅ Healthy with pgvector
- **Celery Worker**: ✅ All tasks loaded successfully
- **Tool Calling**: ✅ Complete implementation
- **RAG System**: ✅ HubSpot contacts and emails synced

---

## **🎯 Quick Health Check**

### **1. System Health**
```bash
# Check all containers
docker ps

# Verify backend health
curl http://localhost:8000/health

# Verify services are responsive
curl -I http://localhost:3000
```

### **2. Data Verification**
The system should have:
- **2 HubSpot contacts** (Shuhel Khan, Shuhel Work)
- **200+ Gmail emails** with embeddings
- **User with both Google + HubSpot OAuth** connected

---

## **🚀 Testing Scenarios - Ready to Execute**

### **Category 1: RAG Functionality Testing**

#### **Test 1.1: HubSpot Contact Queries** ⭐
```
🎯 Query: "Could you list out my hubspot contacts?"
✅ Expected: Returns both HubSpot contacts with clean formatting
🔍 Success Criteria: 
   - Shows Shuhel Khan and Shuhel Work
   - Includes emails and companies
   - Professional formatting
```

#### **Test 1.2: Contact Query Variations**
```
🎯 Try these variations:
   - "Show me all my contacts"
   - "Who are my contacts in HubSpot?"
   - "List contacts from CRM"
✅ Expected: All return HubSpot contact data
```

#### **Test 1.3: Meeting Invitations** ⭐
```
🎯 Query: "Pull my meeting invitations"
✅ Expected: Returns 10 meeting-related emails
🔍 Success Criteria: 
   - Finds meetings, calendar invites, scheduled calls
   - Comprehensive coverage (not just 3 results)
   - Recent and relevant results
```

#### **Test 1.4: Email Context Search**
```
🎯 Query: "Show me emails about financial planning"
✅ Expected: Returns relevant emails with financial context
```

#### **Test 1.5: Mixed Data Integration**
```
🎯 Query: "What's my recent activity with clients?"
✅ Expected: Combines HubSpot contacts + recent emails + meetings
```

---

### **Category 2: Tool Calling Testing** ⭐

#### **Test 2.1: Send Email**
```
🎯 Query: "Send an email to john@example.com about our meeting tomorrow"
✅ Expected: 
   - AI extracts: to=john@example.com, subject, body
   - Sends real email via Gmail API
   - Returns confirmation with email details
🔍 Verification: Check Gmail sent folder
```

#### **Test 2.2: Create Calendar Event**
```
🎯 Query: "Schedule a meeting with Sarah Johnson next Tuesday at 2pm for 1 hour"
✅ Expected:
   - AI extracts: title, date/time, duration
   - Creates real Google Calendar event
   - Returns event link and confirmation
🔍 Verification: Check Google Calendar
```

#### **Test 2.3: Create HubSpot Contact**
```
🎯 Query: "Create a new contact for Mike Chen at TechCorp, email mike.chen@techcorp.com"
✅ Expected:
   - AI extracts: name, company, email
   - Creates real HubSpot contact
   - Returns HubSpot contact ID
🔍 Verification: Check HubSpot CRM
```

#### **Test 2.4: Complex Multi-Action**
```
🎯 Query: "Send a follow-up email to my HubSpot contact Shuhel Khan and schedule a call for Friday"
✅ Expected:
   - RAG finds Shuhel Khan's details
   - Sends email using found contact info
   - Creates calendar event
   - Both actions completed successfully
```

---

### **Category 3: End-to-End Workflows**

#### **Test 3.1: Client Outreach Workflow** ⭐
```
Step 1: "Who are my HubSpot contacts?"
Step 2: "Send an email to Shuhel Khan about a quarterly review meeting"
Step 3: "Schedule the meeting for next Wednesday at 3pm"

✅ Expected: Complete workflow with context awareness
```

#### **Test 3.2: Financial Advisory Scenario**
```
🎯 Query: "I need to follow up with clients about their Q4 financial planning. Show me my contacts and help me send personalized emails"
✅ Expected: 
   - Lists HubSpot contacts
   - Offers personalized email suggestions
   - Can execute actions
```

---

### **Category 4: AI Intelligence Testing**

#### **Test 4.1: Context Awareness**
```
🎯 Query: "What should I know about my client relationships?"
✅ Expected: 
   - Analyzes HubSpot contacts
   - Reviews recent email interactions
   - Provides professional insights
```

#### **Test 4.2: Professional Advisory Tone**
```
🎯 All responses should:
   - Sound like a professional financial advisor
   - Use appropriate business language
   - Provide actionable insights
   - Never claim "I don't have access to your data"
```

---

## **📋 Testing Steps**

### **1. Access the Application**
```bash
# Open in browser
open http://localhost:3000

# Login with Google OAuth
# Connect HubSpot integration
```

### **2. Start with Priority Tests** ⭐
Execute these high-priority tests first:
1. **HubSpot Contact Query** (Test 1.1)
2. **Meeting Invitations** (Test 1.3)  
3. **Send Email** (Test 2.1)
4. **Create Calendar Event** (Test 2.2)
5. **Client Outreach Workflow** (Test 3.1)

### **3. Verify Real Actions**
- Check Gmail sent folder for emails
- Check Google Calendar for events
- Check HubSpot CRM for new contacts

---

## **🎯 Success Criteria**

### **MVP Success Indicators**
- ✅ RAG system finds relevant data consistently
- ✅ Tool calling executes real actions (email, calendar, contacts)
- ✅ AI provides professional financial advisor responses
- ✅ System handles errors gracefully
- ✅ End-to-end workflows complete successfully

### **Performance Benchmarks**
- **Query Response Time**: < 3 seconds
- **Tool Execution Time**: < 5 seconds
- **System Uptime**: 100% during testing
- **Success Rate**: > 90% of interactions

---

## **🐛 Troubleshooting**

### **Common Issues**
1. **"I don't have access"** responses → Check RAG system
2. **Tool calls not executing** → Verify OAuth tokens
3. **No data found** → Check sync status
4. **Slow responses** → Check database/embeddings

### **Quick Fixes**
```bash
# Restart services
docker-compose restart

# Check logs
docker logs jump-assessment-backend-1
docker logs jump-assessment-celery_worker-1

# Verify data
docker exec -it jump-assessment-db-1 psql -U postgres -d financial_agent
SELECT COUNT(*) FROM emails;
SELECT COUNT(*) FROM hubspot_contacts;
```

---

## **🚀 Ready to Test!**

**System Status**: ✅ All services operational
**Data Status**: ✅ HubSpot contacts and Gmail emails synced  
**Tools Status**: ✅ Email, Calendar, HubSpot contact creation ready
**Testing URL**: http://localhost:3000

Start with the ⭐ priority tests and work through each category systematically! 