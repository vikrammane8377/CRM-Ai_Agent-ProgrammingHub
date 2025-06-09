#!/usr/bin/env python3
# run_agent.py - Script to run the educational app agent with automatic setup

import os
import sys
import argparse
import uuid
import time
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Import agent functions
from agent_main_with_mongodb import create_agent, reply_to_user, log_message, log_error

# Import Gmail and Sheets services
try:
    from gmail_mongodb_integration import get_gmail_service
    from sheets_service import initialize_sheets, test_log_entry
except Exception as e:
    log_error(f"Error importing Gmail or Sheets services: {str(e)}")
    get_gmail_service = None

def setup_services():
    """Set up Gmail and Google Sheets services."""
    log_message("Setting up services...")
    
    # Initialize Gmail service
    try:
        gmail_service = get_gmail_service()
        log_message("Gmail service initialized successfully.")
    except Exception as e:
        log_error(f"Failed to initialize Gmail service: {str(e)}")
        return False
    
    # Initialize Google Sheets
    try:
        sheets_success = initialize_sheets()
        if sheets_success:
            log_message("Google Sheets initialized successfully.")
            # Test log entry to verify sheets are working
            #test_success = test_log_entry()
            #if test_success:
            #    log_message("Test log entry created successfully.")
            #else:
           #    log_message("Warning: Test log entry failed, but continuing.")
        else:
            log_error("Google Sheets initialization failed.")
            return False
    except Exception as e:
        log_error(f"Error setting up Google Sheets: {str(e)}")
        log_message("Continuing without Google Sheets functionality.")
    
    log_message("Services setup completed successfully.")
    return True

def run_interactive_mode(args):
    """Run the agent in interactive console mode."""
    log_message("Starting interactive mode")
    
    # Determine if MongoDB should be used
    use_mongodb = args.mongodb or args.email and args.thread_id
    
    # For MongoDB mode, either use provided thread_id or generate a new one
    thread_id = args.thread_id
    user_email = args.email
    
    if use_mongodb and not thread_id:
        # Generate a thread ID if not provided
        thread_id = f"console_{uuid.uuid4()}"
        log_message(f"Generated thread ID: {thread_id}")
    
    if use_mongodb and not user_email:
        # Prompt for user email if not provided
        user_email = input("Please enter user email: ").strip()
        if not user_email:
            log_error("Email is required for MongoDB mode")
            return 1
    
    # Create the agent
    agent = create_agent(
        use_mongodb=use_mongodb,
        user_email=user_email,
        thread_id=thread_id
    )
    
    # Display mode information
    print("\n" + "="*60)
    print(f"Educational App CRM Agent {'with MongoDB memory' if use_mongodb else 'with in-memory storage'}")
    if use_mongodb:
        print(f"User Email: {user_email}")
        print(f"Thread ID: {thread_id}")
    print("="*60 + "\n")
    
    # Greet the user
    reply_to_user("Hello! I'm your educational app assistant. How can I help you today?")
    
    # Main interaction loop
    while True:
        query = input("User: ")
        if query.lower() in ['exit', 'quit', 'bye']:
            reply_to_user("Thank you for contacting our support. Have a great day!")
            break
        
        try:
            # Process the query with the agent
            result = agent.invoke({"input": query})
            
            # Use the reply_to_user function to display the agent's response
            if "output" in result:
                reply_to_user(result["output"])
                
        except Exception as e:
            log_error(f"Error processing query: {str(e)}")
            reply_to_user(f"Sorry, I encountered an error: {str(e)}")
    
    return 0

def run_email_mode(args):
    """Run the agent in email monitoring mode."""
    log_message("Starting email monitor mode")
    
    # Import the email monitor function
    from gmail_mongodb_integration import email_monitor_loop
    
    # Run the email monitor loop
    return email_monitor_loop()

def list_threads(args):
    """List all conversation threads for a user."""
    from mongodb_memory_system import MongoDBMemory
    from pymongo import MongoClient
    
    # MongoDB configuration
    mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB_NAME", "xseries-crm")
    collection_name = os.getenv("MONGODB_CONVERSATIONS_COLLECTION", "conversations")
    
    user_email = args.email
    if not user_email:
        user_email = input("Please enter user email to list threads: ").strip()
        if not user_email:
            log_error("Email is required to list threads")
            return 1
    
    # Connect to MongoDB directly
    try:
        client = MongoClient(mongo_uri)
        db = client[db_name]
        collection = db[collection_name]
        
        # Find all threads for this user
        threads = list(collection.find(
            {"user_email": user_email},
            {
                "_id": 0, 
                "thread_id": 1, 
                "created_at": 1, 
                "last_updated": 1,
                "metadata": 1
            }
        ).sort("last_updated", -1))
        
        if not threads:
            print(f"No conversation threads found for {user_email}")
            return 0
        
        print(f"\nFound {len(threads)} conversation threads for {user_email}:")
        for i, thread in enumerate(threads, 1):
            thread_id = thread.get("thread_id")
            created_at = thread.get("created_at", "Unknown")
            last_updated = thread.get("last_updated", "Unknown")
            
            if isinstance(created_at, str):
                created_time = created_at
            else:
                created_time = created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(created_at, 'strftime') else str(created_at)
                
            if isinstance(last_updated, str):
                updated_time = last_updated
            else:
                updated_time = last_updated.strftime("%Y-%m-%d %H:%M:%S") if hasattr(last_updated, 'strftime') else str(last_updated)
            
            # Get metadata for additional info
            metadata = thread.get("metadata", {})
            subject = metadata.get("subject", "No Subject")
            status = metadata.get("status", "Unknown")
            
            print(f"{i}. Thread ID: {thread_id}")
            print(f"   Subject: {subject}")
            print(f"   Created: {created_time}")
            print(f"   Last Activity: {updated_time}")
            print(f"   Status: {status}")
            print("")
        
    except Exception as e:
        log_error(f"Error listing threads: {str(e)}")
        return 1
    
    return 0

def main():
    """Main function to run the agent with various options."""
    parser = argparse.ArgumentParser(description="Educational App CRM Agent")
    parser.add_argument("--mongodb", action="store_true", help="Use MongoDB for memory persistence")
    parser.add_argument("--email", help="User email for MongoDB operations")
    parser.add_argument("--thread-id", help="Thread ID for conversation context")
    parser.add_argument("--email-monitor", action="store_true", help="Run in Gmail monitoring mode")
    parser.add_argument("--list-threads", action="store_true", help="List all conversation threads for a user")
    parser.add_argument("--skip-setup", action="store_true", help="Skip Gmail and Sheets setup")
    
    args = parser.parse_args()
    
    # Set up Gmail and Sheets services, unless skipped
    if not args.skip_setup:
        if not setup_services():
            log_error("Service setup failed. Add --skip-setup to bypass this check.")
            return 1
    
    # List threads mode
    if args.list_threads:
        return list_threads(args)
    
    # Email monitor mode
    if args.email_monitor:
        return run_email_mode(args)
    
    # Default to interactive mode
    return run_interactive_mode(args)

if __name__ == "__main__":
    print("\n" + "="*60)
    print("EDUCATIONAL APP CRM AGENT - STARTUP")
    print("="*60 + "\n")
    
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
        sys.exit(0)
    except Exception as e:
        log_error(f"Unhandled exception: {str(e)}")
        sys.exit(1)