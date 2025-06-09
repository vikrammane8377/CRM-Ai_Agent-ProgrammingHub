#!/usr/bin/env python3
# api_server.py - API server to trigger email checking on demand
import gc
import os
import sys
import traceback
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from gmail_mongodb_integration import (
    get_gmail_service, 
    fetch_emails_after_time, 
    process_email, 
    send_email_reply, 
    test_gmail_connection,
    get_shared_agent,
    log_message,
    log_error,
    mark_message_as_read  # Add this import
)
import time
# Load environment variables
load_dotenv()

# Import email processing functions
from gmail_mongodb_integration import (
    get_gmail_service, 
    fetch_emails_after_time, 
    process_email, 
    send_email_reply, 
    test_gmail_connection,
    get_shared_agent,
    log_message,
    log_error
)

# Create Flask app
app = Flask(__name__)

# Initialize shared services
gmail_service = None
system_prompt = None
PROGRAM_START_TIME = int(time.time())


def initialize_services():
    """Initialize services required for email processing"""
    global gmail_service, system_prompt
    
    try:
        # Check if already initialized
        if gmail_service is not None:
            return True
            
        # Connect to Gmail
        log_message("Initializing Gmail service...")
        if not test_gmail_connection():
            log_error("Failed to connect to Gmail")
            return False
        
        gmail_service = get_gmail_service()
        
        # Preload the shared agent to avoid initialization delay on first request
        get_shared_agent()
        log_message("Shared agent initialized successfully")
        
        # Read system prompt
        try:
            with open('prompts.txt', 'r') as file:
                system_prompt = file.read()
            log_message("System prompt loaded successfully")
        except FileNotFoundError:
            log_error("Warning: prompts.txt file not found! Using default prompt.")
            system_prompt = "You are a helpful assistant for an educational app's customer service."
        
        log_message("All services initialized successfully")
        return True
        
    except Exception as e:
        log_error(f"Error initializing services: {str(e)}")
        traceback.print_exc()
        return False

@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "gmail": gmail_service is not None,
            "agent": get_shared_agent() is not None,
            "system_prompt": system_prompt is not None
        }
    })

@app.route('/process-emails', methods=['GET', 'POST'])
def process_emails_endpoint():
    """API endpoint to trigger email processing for only the latest email"""
    try:
        # Initialize services if not already done
        if not initialize_services():
            return jsonify({
                "status": "error",
                "message": "Failed to initialize services",
                "timestamp": datetime.now().isoformat()
            }), 500
        
        log_message(f"Processing emails since program start: {datetime.fromtimestamp(PROGRAM_START_TIME)}")
        
        # Fetch only the latest new email since program start
        emails = fetch_emails_after_time(gmail_service, PROGRAM_START_TIME, mark_as_read=False, max_results=1)
        
        if not emails:
            log_message("No new emails found")
            return jsonify({
                "status": "success",
                "emails_processed": 0,
                "message": "No new emails found",
                "timestamp": datetime.now().isoformat()
            })
        
        log_message(f"Found {len(emails)} new email to process")
        
        # Process the single email
        processed = 0
        responses_sent = 0
        errors = 0
        
        # There should only be one email in the list
        email = emails[0]
        try:
            # Process the email
            result = process_email(email, system_prompt)
            
            # Mark as read after processing
            mark_message_as_read(gmail_service, email['id'])
            log_message(f"Marked message {email['id']} as read")
            
            processed += 1
            
            # Send response if needed
            if result:
                log_message(f"Generated response for email from {result['email']}")
                
                # Send the response
                reply_result = send_email_reply(
                    service=gmail_service,
                    to=result['email'],
                    subject=result['subject'],
                    body_text=result['response'],
                    thread_id=result['thread_id']
                )
                
                if reply_result:
                    log_message(f"Sent response to {result['email']} in thread {result['thread_id']}")
                    responses_sent += 1
                    
                    # Clear agent memory after successful response
                    from agent_main_with_mongodb import clear_agent_memory
                    clear_agent_memory()
                else:
                    log_error(f"Failed to send response to {result['email']}")
                    errors += 1
            else:
                log_message(f"No response needed for message - skipping reply")
                
        except Exception as e:
            log_error(f"Error processing email {email.get('id')}: {str(e)}")
            traceback.print_exc()
            errors += 1
        
        # Force garbage collection after processing
        gc.collect()
        
        # Return results
        return jsonify({
            "status": "success",
            "emails_found": len(emails),
            "emails_processed": processed,
            "responses_sent": responses_sent,
            "errors": errors,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        log_error(f"Error in API endpoint: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500
    
if __name__ == '__main__':
    # Get port from environment or use default
    port = int(os.environ.get('PORT', 8080))
    
    # Initialize services at startup
    initialize_services()
    
    # Start Flask app
    app.run(host='0.0.0.0', port=port, debug=False)