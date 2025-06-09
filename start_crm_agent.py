#!/usr/bin/env python3
# start_crm_agent.py - Main entry point for the CRM agent system

import os
import sys
import time
import argparse
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

def display_banner():
    """Display a nice banner for the application."""
    print("\n" + "="*70)
    print("                   EDUCATIONAL APP CRM AGENT SYSTEM")
    print("="*70)
    print("  A complete customer service solution with MongoDB memory persistence")
    print("-"*70)
    print("  • MongoDB-based conversation memory")
    print("  • Gmail integration for email support")
    print("  • Google Sheets logging for customer interactions")
    print("  • Support for certificate generation, premium activation, and more")
    print("="*70 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Start the CRM Agent System")
    parser.add_argument("--mode", choices=["interactive", "email", "list"], 
                       default="interactive", help="Operation mode")
    parser.add_argument("--email", help="User email (required for some operations)")
    parser.add_argument("--thread-id", help="Thread ID for continuing a conversation")
    parser.add_argument("--skip-setup", action="store_true", help="Skip service setup")
    
    args = parser.parse_args()
    
    # Import after parsing args to avoid slow imports when just displaying help
    from run_agent import setup_services, run_interactive_mode, run_email_mode, list_threads
    
    # Display banner
    display_banner()
    
    # Create arguments for run_agent functions
    run_args = argparse.Namespace()
    run_args.mongodb = True  # Always use MongoDB
    run_args.email = args.email
    run_args.thread_id = args.thread_id
    run_args.email_monitor = args.mode == "email"
    run_args.list_threads = args.mode == "list"
    run_args.skip_setup = args.skip_setup
    
    # Set up services if not skipped
    if not args.skip_setup:
        if not setup_services():
            print("\nService setup failed. If you want to continue anyway, use --skip-setup")
            print("Fix any service issues and try again.\n")
            return 1
    
    # Run the appropriate mode
    if args.mode == "interactive":
        print("\nStarting interactive mode...")
        if not args.email:
            run_args.email = input("Please enter user email for conversation tracking: ").strip()
        return run_interactive_mode(run_args)
    
    elif args.mode == "email":
        print("\nStarting email monitoring mode...")
        return run_email_mode(run_args)
    
    elif args.mode == "list":
        print("\nListing conversation threads...")
        if not args.email:
            run_args.email = input("Please enter user email to list conversations: ").strip()
        return list_threads(run_args)
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnhandled exception: {str(e)}")
        sys.exit(1)






        