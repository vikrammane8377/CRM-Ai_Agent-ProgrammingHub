#!/usr/bin/env python3
# sheets_service.py - Initialize Google Sheets with multiple tabs and columns

import os
import json
import time
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import traceback
from pymongo import MongoClient
# Constants
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', './credentials/service_account.json')
IMPERSONATED_USER = os.getenv('IMPERSONATED_USER', 'admin@programminghub.io')
SCOPES = os.getenv('SCOPES', 'https://www.googleapis.com/auth/spreadsheets').split(',')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', '1zOltp3IBsZ2GRmTxh-ob1fFoaK5SHxba261yVaau7AM')
    
# Define sheet structures
SHEETS_CONFIG = {
    'All-Logs': [
        'Timestamp', 'Issue Type', 'App Name', 'Email', 
         'Initial Message', 'Status', 
    ],
    'Technical_Issues': [
        'Timestamp', 'App Name', 'Email', 'Issue Description', 
        'Device', 'OS Version', 'App Version', 'Screenshot'
    ],
    'Certificate_Issues': [
        'Timestamp', 'App Name', 'Email', 'Course', 
         'New Name'
    ],
    'Subscription_Issues': [
        'Timestamp', 'App Name', 'Email', 'Order ID', 
          'Status'
    ],
    'Refund': [
        'Timestamp', 'App Name', 'Email', 'Order ID', 
         'Status'
    ],
    'Account_Deletion': [
        'Timestamp', 'App Name', 'Email',
         'Status',
    ],
    'Payment_Issues': [
    'Timestamp', 'App Name', 'Email', 'Country', 'Initial Message', 'Status',
]
}

def log_message(message):
    """Simple logging function"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] INFO: {message}")

def log_error(message):
    """Simple error logging function"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] ERROR: {message}")

def get_sheets_service():
    """Initialize Google Sheets service using service account credentials"""
    try:
        # Check if SERVICE_ACCOUNT_FILE is a file path or JSON string
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            # Load from file
            log_message(f"Loading service account from file: {SERVICE_ACCOUNT_FILE}")
            creds = Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE,
                scopes=SCOPES
            )
        else:
            # Try to parse as JSON string
            try:
                log_message("Loading service account from JSON string")
                service_account_info = json.loads(SERVICE_ACCOUNT_FILE)
                creds = Credentials.from_service_account_info(
                    service_account_info,
                    scopes=SCOPES
                )
            except json.JSONDecodeError:
                log_error(f"Service account is neither a valid file path nor JSON string: {SERVICE_ACCOUNT_FILE}")
                raise ValueError(f"Invalid service account format: {SERVICE_ACCOUNT_FILE}")
        
        # Build the Sheets API service
        service = build('sheets', 'v4', credentials=creds)
        log_message("Google Sheets service initialized successfully with service account")
        return service
    except Exception as e:
        log_error(f"Error initializing Google Sheets service: {str(e)}")
        raise

def get_existing_sheets():
    """Get a list of existing sheets in the spreadsheet"""
    try:
        service = get_sheets_service()
        spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheets = spreadsheet.get('sheets', [])
        
        existing_sheets = []
        for sheet in sheets:
            existing_sheets.append(sheet['properties']['title'])
        
        log_message(f"Found existing sheets: {', '.join(existing_sheets)}")
        return existing_sheets
    except Exception as e:
        log_error(f"Error getting existing sheets: {str(e)}")
        raise

def create_sheet(sheet_name):
    """Create a new sheet with the given name"""
    try:
        service = get_sheets_service()
        
        # Create the sheet
        body = {
            'requests': [{
                'addSheet': {
                    'properties': {
                        'title': sheet_name
                    }
                }
            }]
        }
        
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=body
        ).execute()
        
        log_message(f"Created new sheet: {sheet_name}")
        return True
    except HttpError as error:
        if 'already exists' in str(error):
            log_message(f"Sheet '{sheet_name}' already exists")
            return True
        log_error(f"Error creating sheet '{sheet_name}': {error}")
        return False

def add_headers(sheet_name, headers):
    """Add header row to the specified sheet"""
    try:
        service = get_sheets_service()
        
        # First, check if headers are already there
        range_name = f"{sheet_name}!A1:Z1"
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        if values and len(values[0]) >= len(headers):
            log_message(f"Headers already exist in sheet '{sheet_name}'")
            return True
        
        # Add the headers
        body = {
            'values': [headers]
        }
        
        response = service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet_name}!A1",
            valueInputOption='RAW',
            body=body
        ).execute()
        
        log_message(f"Added headers to sheet '{sheet_name}'")
        
        # Format the header row
        format_request = {
            'requests': [{
                'repeatCell': {
                    'range': {
                        'sheetId': get_sheet_id(sheet_name),
                        'startRowIndex': 0,
                        'endRowIndex': 1
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'backgroundColor': {
                                'red': 0.8,
                                'green': 0.8,
                                'blue': 0.8
                            },
                            'horizontalAlignment': 'CENTER',
                            'textFormat': {
                                'bold': True
                            }
                        }
                    },
                    'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
                }
            }]
        }
        
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=format_request
        ).execute()
        
        log_message(f"Formatted headers in sheet '{sheet_name}'")
        return True
    except Exception as e:
        log_error(f"Error adding headers to sheet '{sheet_name}': {str(e)}")
        return False

def get_sheet_id(sheet_name):
    """Get the sheet ID for a given sheet name"""
    try:
        service = get_sheets_service()
        spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheets = spreadsheet.get('sheets', [])
        
        for sheet in sheets:
            if sheet['properties']['title'] == sheet_name:
                return sheet['properties']['sheetId']
        
        log_error(f"Sheet '{sheet_name}' not found")
        return None
    except Exception as e:
        log_error(f"Error getting sheet ID for '{sheet_name}': {str(e)}")
        return None

def format_sheet(sheet_name):
    """Apply basic formatting to the sheet"""
    try:
        service = get_sheets_service()
        sheet_id = get_sheet_id(sheet_name)
        
        if not sheet_id:
            log_error(f"Cannot format sheet '{sheet_name}': Sheet ID not found")
            return False
        
        # Define formatting request
        format_request = {
            'requests': [
                # Freeze the header row
                {
                    'updateSheetProperties': {
                        'properties': {
                            'sheetId': sheet_id,
                            'gridProperties': {
                                'frozenRowCount': 1
                            }
                        },
                        'fields': 'gridProperties.frozenRowCount'
                    }
                },
                # Auto-resize columns
                {
                    'autoResizeDimensions': {
                        'dimensions': {
                            'sheetId': sheet_id,
                            'dimension': 'COLUMNS',
                            'startIndex': 0,
                            'endIndex': 26  # A through Z
                        }
                    }
                }
            ]
        }
        
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=format_request
        ).execute()
        
        log_message(f"Applied formatting to sheet '{sheet_name}'")
        return True
    except Exception as e:
        log_error(f"Error formatting sheet '{sheet_name}': {str(e)}")
        return False

def initialize_sheets():
    """Initialize all sheets with their respective headers"""
    try:
        # Get existing sheets to check what we need to create
        existing_sheets = get_existing_sheets()
        
        # Process each sheet in the configuration
        for sheet_name, headers in SHEETS_CONFIG.items():
            # Create the sheet if it doesn't exist
            if sheet_name not in existing_sheets:
                success = create_sheet(sheet_name)
                if not success:
                    continue
            
            # Add headers to the sheet
            success = add_headers(sheet_name, headers)
            if not success:
                continue
            
            # Apply formatting to the sheet
            format_sheet(sheet_name)
        
        log_message("All sheets have been initialized successfully")
        return True
    except Exception as e:
        log_error(f"Error initializing sheets: {str(e)}")
        return False

def log_to_sheet(sheet_name, row_data):
    """Log a row of data to a specific sheet at the top (newest entries first)"""
    try:
        service = get_sheets_service()
        
        # First, get the current data in the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet_name}!A:Z"
        ).execute()
        
        values = result.get('values', [])
        
        # If there are no values or only headers, append normally
        if len(values) <= 1:
            # Prepare the request for append
            body = {
                'values': [row_data]
            }
            
            # Execute the append request
            result = service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{sheet_name}!A:Z",
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            
            log_message(f"Data logged to {sheet_name}: {result.get('updates').get('updatedRange')}")
            return True
        
        # If there are existing values, insert at row 2 (after headers)
        else:
            # Prepare the request for insert
            body = {
                'values': [row_data]
            }
            
            # Execute the insert request
            result = service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{sheet_name}!A2",
                valueInputOption='RAW',
                body=body
            ).execute()
            
            # Now shift existing data down one row (excluding header)
            shift_request = {
                'requests': [{
                    'insertRange': {
                        'range': {
                            'sheetId': get_sheet_id(sheet_name),
                            'startRowIndex': 1,  # Row index after header
                            'endRowIndex': 2     # Insert one row
                        },
                        'shiftDimension': 'ROWS'
                    }
                }]
            }
            
            service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body=shift_request
            ).execute()
            
            log_message(f"Data logged to top of {sheet_name}")
            return True
            
    except Exception as e:
        log_error(f"Error logging to {sheet_name}: {str(e)}")
        return False

# Add the logging functions that agent_main.py is importing

def log_certificate_issue(app_name, email, course, new_name, initial_message=None, status="Open"):
    """Log a certificate issue to both the All-Logs and Certificate_Issues sheets"""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Log to Certificate_Issues sheet
        cert_data = [
            timestamp,
            app_name,
            email,
            course,
            new_name
        ]
        
        cert_success = log_to_sheet("Certificate_Issues", cert_data)
        
        # Log to All-Logs sheet
        all_logs_data = [
            timestamp,
            "Certificate Issue",
            app_name,
            email,
            initial_message if initial_message else "Certificate name change requested",
            status
        ]
        
        all_logs_success = log_to_sheet("All-Logs", all_logs_data)
        
        return cert_success and all_logs_success
    except Exception as e:
        log_error(f"Error logging certificate issue: {str(e)}")
        return False

def log_subscription_issue(app_name, email, order_id, initial_message=None, status="Open"):
    """Log a subscription issue to both the All-Logs and Subscription_Issues sheets"""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Log to Subscription_Issues sheet
        sub_data = [
            timestamp,
            app_name,
            email,
            order_id,
            status
        ]
        
        sub_success = log_to_sheet("Subscription_Issues", sub_data)
        
        # Log to All-Logs sheet
        all_logs_data = [
            timestamp,
            "Subscription Issue",
            app_name,
            email,
            initial_message if initial_message else "Subscription activation issue",
            status
        ]
        
        all_logs_success = log_to_sheet("All-Logs", all_logs_data)
        
        return sub_success and all_logs_success
    except Exception as e:
        log_error(f"Error logging subscription issue: {str(e)}")
        return False
    
def log_payment_issue(app_name, email, initial_message=None, country=None, status="Open"):
    """Log a payment issue to both the All-Logs and Payment_Issues sheets"""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Log to Payment_Issues sheet
        payment_data = [
            timestamp,
            app_name,
            email,
            country if country else "Not provided",
            initial_message if initial_message else "Payment processing issue",
            status
        ]
        
        payment_success = log_to_sheet("Payment_Issues", payment_data)
        
        # Log to All-Logs sheet
        all_logs_data = [
            timestamp,
            "Payment Issue",
            app_name,
            email,
            initial_message if initial_message else "Payment processing issue",
            status
        ]
        
        all_logs_success = log_to_sheet("All-Logs", all_logs_data)
        
        return payment_success and all_logs_success
    except Exception as e:
        log_error(f"Error logging payment issue: {str(e)}")
        return False

def log_technical_issue(app_name, email, issue_description, device=None, os_version=None, app_version=None, status="Open", thread_id=None):
    """Log a technical issue with screenshot if available"""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_message(f"Logging technical issue with thread_id: {thread_id}")
        
        # Get screenshot URLs from metadata if available
        screenshot_urls = []
        if thread_id:
            try:
                # Import mongodb functions
                from mongodb_memory import MongoDBMemory, MongoDBChatMessageHistory
                from gmail_mongodb_integration import MONGODB_URI
                # Get MongoDB connection details
                mongo_uri = MONGODB_URI
                db_name = os.getenv("MONGODB_DB_NAME", "xseries-crm")
                collection_name = os.getenv("MONGODB_CONVERSATIONS_COLLECTION", "conversations")
                
                # Connect to MongoDB
                client = MongoClient(mongo_uri)
                db = client[db_name]
                collection = db[collection_name]
                
                # Get screenshot links from metadata
                log_message(f"Searching for thread_id: {thread_id} in MongoDB")
                thread_data = collection.find_one({"thread_id": thread_id})
                
                if thread_data:
                    log_message("Thread found in MongoDB")
                    if "metadata" in thread_data:
                        log_message(f"Metadata found: {thread_data['metadata']}")
                        screenshot_links = thread_data["metadata"].get("screenshot_drive_links", [])
                        log_message(f"Found {len(screenshot_links)} screenshot links: {screenshot_links}")
                        
                        for link_data in screenshot_links:
                            if 'url' in link_data:
                                screenshot_urls.append(link_data['url'])
                                log_message(f"Adding URL to list: {link_data['url']}")
                    else:
                        log_message("No metadata found in thread data")
                else:
                    log_message(f"Thread {thread_id} not found in MongoDB")
            except Exception as e:
                log_error(f"Error retrieving screenshot data: {str(e)}")
                traceback.print_exc()
        
        # Prepare images column content
        screenshots_text = ""
        if screenshot_urls:
                log_message(f"Adding {len(screenshot_urls)} screenshot URLs as plain text")
                screenshots_text = "\n".join(screenshot_urls)
                log_message(f"Added URLs: {screenshots_text}")
        else:
            screenshots_text = "See screenshots column"
            log_message("No screenshots found, using default text")
        
        # Log to Technical_Issues sheet with the standard approach first
        tech_data = [
            timestamp,
            app_name,
            email,
            issue_description,
            device if device else "Not provided",
            os_version if os_version else "Not provided",
            app_version if app_version else "Not provided",
            screenshots_text  # This will contain either the IMAGE formula or default text
        ]
        
        # Get sheet service
        service = get_sheets_service()
        
        # Find the next available row
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Technical_Issues!A:H"
        ).execute()
        values = result.get('values', [])
        next_row = len(values) + 1
        log_message(f"Next available row in Technical_Issues sheet: {next_row}")
        
        # Insert data with standard method first
        body = {
            'values': [tech_data]
        }
        
        result = service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"Technical_Issues!A{next_row}",
            valueInputOption="RAW",
            body=body
        ).execute()
        log_message(f"Base data inserted into Technical_Issues!A{next_row}:H{next_row}")
        
        # Now update the screenshots column with formulas if we have screenshots
        if screenshot_urls:
            formula_body = {
                'values': [[screenshots_text]]
            }
            
            result = service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Technical_Issues!H{next_row}",
                valueInputOption="USER_ENTERED",  # Important for formulas
                body=formula_body
            ).execute()
            
            log_message(f"Updated cell H{next_row} with {len(screenshot_urls)} IMAGE formulas")
        
        # Also log to All-Logs sheet (without screenshots)
        all_logs_data = [
            timestamp,
            "Technical Issue",
            app_name,
            email,
            issue_description,
            status
        ]
        
        all_logs_success = log_to_sheet("All-Logs", all_logs_data)
        log_message(f"Logged to All-Logs sheet: {'Success' if all_logs_success else 'Failed'}")
        
        return True
        
    except Exception as e:
        log_error(f"Error logging technical issue: {str(e)}")
        traceback.print_exc()
        return False
    
def get_drive_service():
    """Initialize Google Drive service using service account credentials"""
    try:
        # Add Drive scope to existing scopes
        drive_scopes = SCOPES + ['https://www.googleapis.com/auth/drive.file']
        
        # Check if SERVICE_ACCOUNT_FILE is a file path or JSON string
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            # Load from file
            log_message(f"Loading service account from file: {SERVICE_ACCOUNT_FILE}")
            creds = Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE,
                scopes=drive_scopes
            )
        else:
            # Try to parse as JSON string
            try:
                log_message("Loading service account from JSON string")
                service_account_info = json.loads(SERVICE_ACCOUNT_FILE)
                creds = Credentials.from_service_account_info(
                    service_account_info,
                    scopes=drive_scopes
                )
            except json.JSONDecodeError:
                log_error(f"Service account is neither a valid file path nor JSON string: {SERVICE_ACCOUNT_FILE}")
                raise ValueError(f"Invalid service account format: {SERVICE_ACCOUNT_FILE}")
        
        # Build the Drive API service
        service = build('drive', 'v3', credentials=creds)
        log_message("Google Drive service initialized successfully with service account")
        return service
    except Exception as e:
        log_error(f"Error initializing Google Drive service: {str(e)}")
        raise
    
def cleanup_drive_files(thread_id):
    """Clean up Drive files associated with a thread ID"""
    if not thread_id:
        return
        
    try:
        # Import mongodb functions
        from mongodb_memory import MongoDBMemory
        from pymongo import MongoClient
        
        # Get MongoDB connection details
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        db_name = os.getenv("MONGODB_DB_NAME", "xseries-crm")
        collection_name = os.getenv("MONGODB_CONVERSATIONS_COLLECTION", "conversations")
        
        # Connect to MongoDB
        client = MongoClient(mongo_uri)
        db = client[db_name]
        collection = db[collection_name]
        
        # Get file IDs from metadata
        thread_data = collection.find_one({"thread_id": thread_id})
        if thread_data and "metadata" in thread_data:
            screenshot_links = thread_data["metadata"].get("screenshot_drive_links", [])
            
            if screenshot_links:
                # Get Drive service
                drive_service = get_drive_service()
                
                # Delete each file
                for link_data in screenshot_links:
                    file_id = link_data.get('id')
                    if file_id:
                        try:
                            drive_service.files().delete(fileId=file_id).execute()
                            log_message(f"Deleted Drive file: {file_id}")
                        except Exception as e:
                            log_error(f"Error deleting Drive file {file_id}: {str(e)}")
                
                # Update metadata to clear screenshot links
                collection.update_one(
                    {"thread_id": thread_id},
                    {"$set": {"metadata.screenshot_drive_links": []}}
                )
                log_message(f"Cleaned up {len(screenshot_links)} screenshot files from Drive")
    except Exception as e:
        log_error(f"Error cleaning up Drive files: {str(e)}")

def log_refund_request(app_name, email, order_id, initial_message=None, status="Pending"):
    """Log a refund request to both the All-Logs and Refund sheets"""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Log to Refund sheet
        refund_data = [
            timestamp,
            app_name,
            email,
            order_id,
            status
        ]
        
        refund_success = log_to_sheet("Refund", refund_data)
        
        # Log to All-Logs sheet
        all_logs_data = [
            timestamp,
            "Refund Request",
            app_name,
            email,
            initial_message if initial_message else "Customer requested refund",
            status
        ]
        
        all_logs_success = log_to_sheet("All-Logs", all_logs_data)
        
        return refund_success and all_logs_success
    except Exception as e:
        log_error(f"Error logging refund request: {str(e)}")
        return False

def log_account_deletion(app_name, email, initial_message=None, status="Pending"):
    """Log an account deletion request to both the All-Logs and Account_Deletion sheets"""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Log to Account_Deletion sheet
        deletion_data = [
            timestamp,
            app_name,
            email,
            status
        ]
        
        deletion_success = log_to_sheet("Account_Deletion", deletion_data)
        
        # Log to All-Logs sheet
        all_logs_data = [
            timestamp,
            "Account Deletion",
            app_name,
            email,
            initial_message if initial_message else "Account deletion requested",
            status
        ]
        
        all_logs_success = log_to_sheet("All-Logs", all_logs_data)
        
        return deletion_success and all_logs_success
    except Exception as e:
        log_error(f"Error logging account deletion: {str(e)}")
        return False

def test_log_entry():
    """Add a test entry to the All-Logs sheet"""
    try:
        # Create a test entry
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        test_entry = [
            timestamp,
            "Test Issue",
            "TestApp",
            "test@example.com",
            "This is a test entry",
            "Open"
        ]
        
        # Append the test entry to the All-Logs sheet
        success = log_to_sheet("All-Logs", test_entry)
        
        if success:
            log_message("Added test entry to All-Logs sheet")
        
        return success
    except Exception as e:
        log_error(f"Error adding test entry: {str(e)}")
        return False

if __name__ == "__main__":
    print("Initializing Google Sheets for CRM logging...")
    
    # Initialize all sheets
    success = initialize_sheets()
    
    if success:
        # Add a test entry to confirm it's working
        #test_success = test_log_entry()
        
        if test_success:
            print("\nGoogle Sheets initialization and test successful! ✅")
        else:
            print("\nSheets initialized but test entry failed! ⚠️")
    else:
        print("\nGoogle Sheets initialization failed! ❌")
    
    print("\nYou can now use these sheets for logging CRM interactions.")