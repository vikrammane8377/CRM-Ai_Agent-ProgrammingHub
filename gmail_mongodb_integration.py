#!/usr/bin/env python3
# gmail_mongodb_integration.py
# Integrates Gmail service with MongoDB memory for persistent conversations using a single shared agent
import traceback  
import os
import gc
from urllib.parse import quote_plus
import pytesseract
from PIL import Image
import tempfile
from googleapiclient.http import MediaInMemoryUpload
import re
from html import unescape
import sys
import time
import json
import uuid
import datetime

# Or if you prefer to be more specific:
from datetime import datetime, timezone
import base64
import re
import traceback
from email.utils import parseaddr
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import ssl
import socket
from google.api_core import retry as gcp_retry
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from googleapiclient.http import MediaInMemoryUpload
from sheets_service import get_drive_service
from mongodb_memory import MongoDBMemory, MongoDBChatMessageHistory

# Import agent functions
from agent_main_with_mongodb import get_shared_agent, process_with_agent, log_message, log_error

# Load environment variables
load_dotenv()

# MongoDB configuration
from urllib.parse import quote_plus

# At the top of gmail_mongodb_integration.py
JUNE_20_START_TIME = int(datetime(2024, 6, 20).timestamp())

DB_NAME = os.getenv("MONGODB_DB_NAME", "xseries-crm")
CONVERSATIONS_COLLECTION = os.getenv("MONGODB_CONVERSATIONS_COLLECTION", "conversations")

# Use MONGODB_URI from .env if present, otherwise build it
MONGODB_URI = os.getenv("MONGODB_URI")

# Gmail API configuration
SCOPES = ['https://www.googleapis.com/auth/gmail.modify', 'https://www.googleapis.com/auth/gmail.send']
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', os.path.join(os.path.dirname(__file__), 'credentials', 'service_account.json'))
IMPERSONATED_USER = os.getenv('IMPERSONATED_USER', 'admin@programminghub.io')

# Define which exceptions we want to retry on
RETRY_EXCEPTIONS = (
    ssl.SSLEOFError,
    socket.error,
    ConnectionError,
    TimeoutError
)


def get_folder_id_by_name(folder_name):
    """Get folder ID by name, create if it doesn't exist"""
    try:
        drive_service = get_drive_service()
        
        # Search for the folder
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        items = results.get('files', [])
        
        # If folder exists, return its ID
        if items:
            #log_message(f"Found existing folder: {folder_name}")
            return items[0]['id']
        
        # If folder doesn't exist, create it
        #log_message(f"Creating new folder: {folder_name}")
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        
        folder = drive_service.files().create(
            body=folder_metadata,
            fields='id'
        ).execute()
        
        return folder.get('id')
        
    except Exception as e:
        log_error(f"Error getting folder ID: {str(e)}")
        return None


def upload_screenshot_to_drive(image_data, sender_email, thread_id, attachment_index):
    """Upload screenshot to Google Drive and return the file's web view link"""
    try:
        # Generate a descriptive filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_email = re.sub(r'[^\w]', '_', sender_email)
        safe_thread_id = re.sub(r'[^\w]', '_', thread_id)
        filename = f"Screenshot_{safe_email}_{timestamp}_{attachment_index}.png"
        
        # Get Drive service
        drive_service = get_drive_service()
        
        # Folder ID for "Technical_Issues_Screenshot"
        # Replace FOLDER_ID_HERE with your actual folder ID
        folder_id = get_folder_id_by_name("Technical_Issues_Screenshot")
        if not folder_id:
            log_error("Failed to find or create the screenshots folder")
            return None

        
        # Create file metadata with the parent folder
        file_metadata = {
            'name': filename,
            'mimeType': 'image/png',
            'parents': [folder_id]  # This specifies where to save the file
        }
        
        # Create a media object from the image data
        media = MediaInMemoryUpload(image_data, mimetype='image/png')
        
        # Upload to Drive
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,webViewLink'
        ).execute()
        
        # Make the file viewable by anyone with the link
        drive_service.permissions().create(
            fileId=file.get('id'),
            body={'type': 'anyone', 'role': 'reader'},
            fields='id'
        ).execute()
        
        #log_message(f"Uploaded screenshot to Drive folder: {file.get('webViewLink')}")
        
        return {
            'id': file.get('id'),
            'url': file.get('webViewLink')
        }
        
    except Exception as e:
        log_error(f"Error uploading screenshot to Drive: {str(e)}")
        traceback.print_exc()
        return None
    
def extract_text_from_image(image_data):
    """
    Extract text from an image using Tesseract OCR.
    
    Args:
        image_data: Binary image data
        
    Returns:
        str: Extracted text or empty string if extraction fails
    """
    try:
        # Create a temporary file to save the image
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
            temp_file.write(image_data)
            temp_file_path = temp_file.name
        
        #log_message(f"Saved image to temporary file: {temp_file_path}")
        
        # Open the image with PIL
        image = Image.open(temp_file_path)
        #log_message(f"Opened image with dimensions: {image.size}")
        
        # Extract text using Tesseract
        extracted_text = pytesseract.image_to_string(image)
        #log_message(f"Extracted text length: {len(extracted_text)}")
        
        # Clean up temporary file
        os.unlink(temp_file_path)
        #log_message("Deleted temporary image file")
        
        # Return the extracted text
        return extracted_text.strip()
    except Exception as e:
        log_error(f"Error extracting text from image: {str(e)}")
        traceback.print_exc()
        return ""

def clean_html_tags(text):
    """
    Cleans HTML tags from text and properly handles HTML entities,
    while preserving the image content marker.
    
    Args:
        text (str): The text that may contain HTML tags and entities
        
    Returns:
        str: Cleaned text with HTML tags removed and entities decoded
    """
    if not text:
        return ""
    
    # Preserve our marker
    has_image_content = "EXTRACTED IMAGE CONTENT" in text
    
    # First unescape any HTML entities like &amp; to &
    text = unescape(text)
    
    # Remove HTML tags
    clean_text = re.sub(r'<[^>]+>', '', text)
    
    # Clean up any extra whitespace that might have been created
    # But preserve newlines for readability of extracted image content
    clean_text = re.sub(r' +', ' ', clean_text)
    lines = [line.strip() for line in clean_text.split('\n')]
    clean_text = '\n'.join(line for line in lines if line)
    
    # Make sure the image content marker is properly formatted if it was present
    if has_image_content and "EXTRACTED IMAGE CONTENT:" not in clean_text:
        if "EXTRACTED IMAGE CONTENT" in clean_text:
            clean_text = clean_text.replace("EXTRACTED IMAGE CONTENT", "EXTRACTED IMAGE CONTENT:")
    
    return clean_text


def clean_email_address(email: str) -> str:
    """Clean and validate email address."""
    if not email:
        return None
        
    # First use parseaddr to handle complex email formats
    name, email = parseaddr(email)
    
    # Remove any surrounding whitespace and angle brackets
    email = email.strip().strip('<>')
    
    # Basic email validation pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if re.match(pattern, email):
        return email
    return None

def get_gmail_service():
    """Initialize Gmail service using service account + domain-wide delegation"""
    try:
        # Check if SERVICE_ACCOUNT_FILE is a file path or JSON string
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            # Load from file
            log_message(f"Loading service account from file: {SERVICE_ACCOUNT_FILE}")
            with open(SERVICE_ACCOUNT_FILE, 'r') as f:
                service_account_info = json.load(f)
        else:
            # Try to parse as JSON string
            try:
                log_message("Loading service account from JSON string")
                service_account_info = json.loads(SERVICE_ACCOUNT_FILE)
            except json.JSONDecodeError:
                log_error(f"Service account is neither a valid file path nor JSON string: {SERVICE_ACCOUNT_FILE}")
                raise ValueError(f"Invalid service account format: {SERVICE_ACCOUNT_FILE}")
            
        # Create credentials from the service account info
        creds = Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPES,
            subject=IMPERSONATED_USER
        )
        
        # Build the Gmail API service
        service = build('gmail', 'v1', credentials=creds)
        log_message("Gmail service initialized successfully with service account")
        return service
    except Exception as e:
        log_error(f"Error initializing Gmail service: {str(e)}")
        raise

def get_full_email_content(service, msg_id, thread_id):
    """Get complete email content including body and extract text from image attachments"""
    try:
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        body_text = ""
        image_extracted_text = []
        screenshot_drive_links = []  # Track Drive links
        
        # Get sender email for metadata
        headers = msg['payload']['headers']
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'No Sender')
        sender_email = extract_email_from_sender(sender)
        
        if 'payload' in msg:
            # Process the message parts recursively
            def process_parts(parts):
                nonlocal body_text, image_extracted_text, screenshot_drive_links
                
                for part in parts:
                    if 'parts' in part:
                        process_parts(part['parts'])
                    
                    # Process text parts
                    if part.get('mimeType', '').startswith('text/'):
                        if 'body' in part and 'data' in part['body']:
                            text_content = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                            body_text += text_content
                    
                    # Process image attachments
                    elif part.get('mimeType', '').startswith('image/'):
                        #log_message(f"Found image attachment with MIME type: {part.get('mimeType')}")
                        if 'body' in part and 'attachmentId' in part['body']:
                            attachment_id = part['body']['attachmentId']
                            #log_message(f"Processing image attachment with ID: {attachment_id}")
                            
                            try:
                                attachment = service.users().messages().attachments().get(
                                    userId='me',
                                    messageId=msg_id,
                                    id=attachment_id
                                ).execute()
                                
                                if 'data' in attachment:
                                    #log_message(f"Successfully retrieved attachment data")
                                    image_data = base64.urlsafe_b64decode(attachment['data'])
                                    
                                    # Extract text using OCR
                                    #log_message(f"Extracting text from image of size {len(image_data)} bytes")
                                    text = extract_text_from_image(image_data)
                                    if text:
                                        #log_message(f"Successfully extracted text from image: {len(text)} characters")
                                        image_extracted_text.append(text)
                                    else:
                                        log_message("No text extracted from image")
                                    
                                    # Upload to Google Drive
                                    drive_result = upload_screenshot_to_drive(
                                        image_data, 
                                        sender_email, 
                                        thread_id, 
                                        len(screenshot_drive_links) + 1
                                    )
                                    
                                    if drive_result:
                                        screenshot_drive_links.append(drive_result)
                                    image_data = None
                            except Exception as e:
                                #log_message(f"Error processing attachment: {str(e)}")
                                traceback.print_exc()
            
            # Start processing the parts
            if 'parts' in msg['payload']:
                process_parts(msg['payload']['parts'])
            else:
                # Handle messages without parts
                if 'body' in msg['payload'] and 'data' in msg['payload']['body']:
                    body_text = base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8', errors='replace')
        
        # Combine body text with extracted image text
        combined_content = body_text.strip()
        
        if image_extracted_text:
            for i, text in enumerate(image_extracted_text):
                if text.strip():
                    if combined_content:
                        combined_content += "\n\n"
                    
                    combined_content += f"EXTRACTED IMAGE CONTENT (Attachment {i+1}):\n"
                    combined_content += text
                    combined_content += "\n"
            
            log_message(f"Added {len(image_extracted_text)} image content extractions to email")
        
        # Store the screenshot links in MongoDB metadata
        if screenshot_drive_links:
            try:
                memory = get_mongodb_memory(sender_email, thread_id)
                if memory:
                    # Add detailed logging
                    log_message(f"About to store links in metadata: {screenshot_drive_links}")
                    
                    # Correctly call update_metadata_field with field name and value as separate parameters
                    memory.update_metadata_field("screenshot_drive_links", screenshot_drive_links)
                    
                    # Verify the update worked
                    doc = memory.chat_memory.collection.find_one({"thread_id": thread_id})
                    if doc and "metadata" in doc and "screenshot_drive_links" in doc["metadata"]:
                        log_message(f"Verified links are in metadata: {doc['metadata']['screenshot_drive_links']}")
                    else:
                        log_error(f"Failed to verify links in metadata after update")
                    
                    log_message(f"Stored {len(screenshot_drive_links)} screenshot links in metadata")
            except Exception as e:
                log_error(f"Error storing screenshot links in metadata: {str(e)}")
                traceback.print_exc()
        
        return combined_content or msg.get('snippet', '')
    except Exception as e:
        log_error(f"Error getting email content: {str(e)}")
        traceback.print_exc()
        return None

def extract_email_from_sender(sender):
    """Extract email address from a sender string."""
    _, email = parseaddr(sender)
    return email.lower()

def mark_message_as_read(service, message_id):
    """Mark a specific email message as read by removing the UNREAD label."""
    try:
        # Modify the message by removing the UNREAD label
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        #log_message(f"Marked message {message_id} as read")
        return True
    except Exception as e:
        log_error(f"Error marking message {message_id} as read: {str(e)}")
        return False


@retry(
    retry=retry_if_exception_type(RETRY_EXCEPTIONS),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    stop=stop_after_attempt(3)
)
def fetch_emails_after_time(service, start_time=None, mark_as_read=False, max_results=1):
    """
    Fetch only the latest unread email received after the given time.
    
    Args:
        service: Gmail API service object
        start_time: Timestamp to look for emails after (defaults to program start time)
        mark_as_read: Whether to mark messages as read during fetching
        max_results: Maximum number of emails to fetch (default: 1 for latest only)
        
    Returns:
        List of email details dictionaries
    """
    try:
        # Use a global variable to store program start time if not already set
        global PROGRAM_START_TIME
        if not start_time:
            # If no start_time provided, use program start time
            if 'PROGRAM_START_TIME' not in globals():
                PROGRAM_START_TIME = int(time.time())
            start_time = PROGRAM_START_TIME
        
        # Convert timestamp to Gmail's expected date format (YYYY/MM/DD)
        start_date = datetime.fromtimestamp(start_time)
        date_str = start_date.strftime('%Y/%m/%d')
        
        log_message("\nFETCHING NEW EMAILS")
        log_message(f"Looking for emails after: {start_date}")
        log_message(f"Using date string: {date_str}")
        
        try:
            # Use Gmail's date format instead of timestamp
            query = f'is:unread after:{date_str}'
            log_message(f"Gmail query: '{query}'")
            
            # Get only the specified number of messages (default is 1)
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            log_message(f"Found {len(messages) if messages else 0} unread message(s) after {date_str}")
            
            # REMOVED: Don't fall back to any unread email if none found after date
            # This allows it to properly process older emails in sequence
            if not messages:
                log_message(f"No unread messages found after {date_str}")
                return []
                
        except Exception as e:
            log_error(f"Error listing messages: {str(e)}")
            return []

        email_details = []
        # Process only the first message (which is the most recent one)
        message = messages[0]  # Just take the first message from the results
        try:
            msg = service.users().messages().get(
                userId='me', 
                id=message['id'], 
                format='full'
            ).execute()
            
            headers = msg['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'No Sender')
            date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'Unknown Date')
            
            # Extract threading headers
            message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), None)
            references = next((h['value'] for h in headers if h['name'].lower() == 'references'), '')
            
            # Format thread ID from Gmail's ID
            thread_id = msg.get('threadId', message['id'])
            
            # Get message timestamp in seconds
            message_timestamp = int(msg['internalDate']) // 1000
            
            # Double-check the timestamp is actually after our start time
            if message_timestamp < start_time:
                log_message(f"Message {message['id']} timestamp {message_timestamp} is before start time {start_time}, skipping")
                return []
            
            # Check if this is a message sent by our system
            from_self = IMPERSONATED_USER.lower() in sender.lower()
            
            # Log message details for debugging
            log_message(f"Processing message: ID={message['id']}, From={sender}, Subject={subject}, Date={date}")
            log_message(f"Message timestamp: {message_timestamp} ({datetime.fromtimestamp(message_timestamp)})")

            # Only process emails that weren't sent by the system itself
            if not from_self:
                # Pass thread_id to get_full_email_content
                content = get_full_email_content(service, message['id'], thread_id)
                
                email_details.append({
                    'id': message['id'],
                    'sender': sender,
                    'subject': subject,
                    'date': date,
                    'content': content,
                    'timestamp': message_timestamp,
                    'thread_id': thread_id,
                    'message_id': message_id,
                    'references': references
                })
                
                # Mark the message as read if requested
                if mark_as_read:
                    mark_message_as_read(service, message['id'])
                    log_message(f"Marked message {message['id']} as read during fetch")
            else:
                log_message(f"Skipping message {message['id']} from self")
                # Still mark our own messages as read to avoid processing them again
                if mark_as_read:
                    mark_message_as_read(service, message['id'])
                    
        except Exception as e:
            log_error(f"Error processing message {message['id']}: {str(e)}")
        
        return email_details
        
    except Exception as e:
        log_error(f"Error fetching emails: {str(e)}")
        traceback.print_exc()
        return []

@retry(
    retry=retry_if_exception_type(RETRY_EXCEPTIONS),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    stop=stop_after_attempt(3)
)
def send_email_reply(service, to, subject, body_text, thread_id=None, attachments=None):
    """Send email reply with retry logic and improved validation"""
    try:
        # Clean and validate the recipient email
        clean_to = clean_email_address(to)
        if not clean_to:
            log_error(f"Invalid email address: {to}")
            return False
            
        #log_message(f"Attempting to send email to: {clean_to}")
        #log_message(f"Thread ID: {thread_id}")
        
        message = MIMEMultipart()
        message['to'] = clean_to
        message['from'] = IMPERSONATED_USER
        
        # Clean subject line
        clean_subject = subject.strip()
        message['subject'] = 'Re: ' + clean_subject if not clean_subject.lower().startswith('re:') else clean_subject
        
        message.attach(MIMEText(body_text))

        # Check if response is asking for order ID
        if "order id" in body_text.lower() and any(word in body_text.lower() for word in ["provide", "send", "where", "find"]):
            # Attach order ID reference images
            reference_images = [
                "reference_Images/Android_receipt.png",
                "reference_Images/ios_receipt.png"
            ]
            
            for img_path in reference_images:
                if os.path.exists(img_path):
                    try:
                        with open(img_path, 'rb') as f:
                            part = MIMEBase('image', 'png')
                            part.set_payload(f.read())
                            encoders.encode_base64(part)
                            part.add_header(
                                'Content-Disposition',
                                f'attachment; filename="{os.path.basename(img_path)}"'
                            )
                            message.attach(part)
                            #log_message(f"Attached order ID reference image: {img_path}")
                    except Exception as e:
                        log_error(f"Error attaching reference image {img_path}: {str(e)}")
                else:
                    log_error(f"Reference image not found: {img_path}")

        # Look for certificate files in the certificates directory
        certificate_files = []
        if os.path.exists('certificates'):
            for file in os.listdir('certificates'):
                if file.endswith('.pdf'):
                    certificate_files.append(os.path.join('certificates', file))
        
        if certificate_files:
            #log_message(f"Found {len(certificate_files)} certificate files to attach")
            
            # Attach all certificate files
            for cert_file in certificate_files:
                try:
                    with open(cert_file, 'rb') as f:
                        part = MIMEBase('application', 'pdf')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename="{os.path.basename(cert_file)}"'
                        )
                        message.attach(part)
                        #log_message(f"Attached certificate file: {cert_file}")
                except Exception as e:
                    log_error(f"Error attaching certificate file {cert_file}: {str(e)}")

        if thread_id:
            try:
                original_msg = service.users().messages().get(
                    userId='me', 
                    id=thread_id, 
                    format='metadata',
                    metadataHeaders=['Message-ID', 'References']
                ).execute()
                
                headers = original_msg.get('payload', {}).get('headers', [])
                message_id = next((h['value'] for h in headers if h['name'] == 'Message-ID'), None)
                references = next((h['value'] for h in headers if h['name'] == 'References'), '')
                
                if message_id:
                    message['References'] = f"{references} {message_id}" if references else message_id
                    message['In-Reply-To'] = message_id
                    #log_message(f"Added threading headers for thread: {thread_id}")
            except Exception as e:
                log_error(f"Error setting up threading: {str(e)}")

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        body = {'raw': raw}
        if thread_id:
            body['threadId'] = thread_id

        @gcp_retry.Retry(predicate=gcp_retry.if_exception_type(RETRY_EXCEPTIONS))
        def send_with_retry():
            return service.users().messages().send(
                userId='me',
                body=body
            ).execute()

        result = send_with_retry()
        #log_message(f"Email sent successfully. Message ID: {result.get('id')}")
        
        # Clear the certificates directory after sending
        if certificate_files:
            for cert_file in certificate_files:
                try:
                    os.remove(cert_file)
                    #log_message(f"Deleted certificate file: {cert_file}")
                except Exception as e:
                    log_error(f"Error deleting certificate file {cert_file}: {str(e)}")
            
            # Check if there are any files left in the directory
            remaining_files = os.listdir('certificates') if os.path.exists('certificates') else []
            #log_message(f"Certificates directory has {len(remaining_files)} files remaining after cleanup")
        
        return result

    except Exception as e:
        log_error(f"Error sending email: {str(e)}")
        log_error(f"Traceback: {traceback.format_exc()}")
        raise  # Re-raise to trigger retry
def attach_reference_images(message, image_types):
    """Attach reference images to an email based on type"""
    reference_images_dir = "reference_images"
    
    if "order_id" in image_types:
        # Attach both iOS and Android order ID reference images
        images = [
            os.path.join(reference_images_dir, "order_id_ios.png"),
            os.path.join(reference_images_dir, "order_id_android.png")
        ]
        
        for img_path in images:
            if os.path.exists(img_path):
                try:
                    with open(img_path, 'rb') as f:
                        part = MIMEBase('image', 'png')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename="{os.path.basename(img_path)}"'
                        )
                        message.attach(part)
                        #log_message(f"Attached reference image: {img_path}")
                except Exception as e:
                    log_error(f"Error attaching reference image {img_path}: {str(e)}")
            else:
                log_error(f"Reference image not found: {img_path}")
    
    return message
def get_mongodb_memory(user_email, thread_id):
    """Get or create a MongoDB-based memory for a specific conversation."""
    try:
        # Create MongoDB memory for this conversation
        memory = MongoDBMemory(
            db_name=DB_NAME,
            collection_name=CONVERSATIONS_COLLECTION,
            user_email=user_email,
            thread_id=thread_id,
            memory_key="chat_history",
            return_messages=True
        )
        return memory
    except Exception as e:
        log_error(f"Error creating MongoDB memory: {str(e)}")
        traceback.print_exc()
        return None

def extract_certificate_paths(text):
    """
    Extract certificate file paths from response text.
    Looks for certificate paths in the certificates directory.
    """
    import re
    import os
    
    # Look for paths that include 'certificates/' or 'certificates\'
    certificate_paths = []
    
    # Use regex to find certificate paths
    matches = re.findall(r"['\"]?(certificates/[^'\"]+?\.pdf)['\"]?", text)
    if matches:
        for match in matches:
            path = match.strip("'\"")
            if os.path.exists(path):
                certificate_paths.append(path)
    
    # If no explicit paths found, look for any certificate files in the certificates directory
    if not certificate_paths and os.path.exists('certificates'):
        import time
        
        for file in os.listdir('certificates'):
            if file.startswith('certificate_') and file.endswith('.pdf'):
                # Check if the file was created in the last minute
                file_path = os.path.join('certificates', file)
                file_creation_time = os.path.getctime(file_path)
                if time.time() - file_creation_time < 60:  # Within the last minute
                    certificate_paths.append(file_path)
    
    return certificate_paths

# In gmail_mongodb_integration.py
import gc  # Add this import at the top if not already present

def process_email(email_data, system_prompt):
    """Process a single email and generate a response using the shared agent."""
    try:
        # Extract relevant information
        sender = email_data.get('sender', 'Unknown Sender')
        subject = email_data.get('subject', 'No Subject')
        content = email_data.get('content', '')
        thread_id = email_data.get('thread_id', email_data.get('id'))
        
        print(f"[INFO] Processing email from {extract_email_from_sender(sender)} with thread ID: {thread_id}")
        print(f"[INFO] Subject: {subject}")
        
        # Clean HTML tags from content
        cleaned_content = clean_html_tags(content)
        print(f"[INFO] Original content length: {len(content)}, Cleaned content length: {len(cleaned_content)}")
        
        # Extract email address from sender string
        user_email = extract_email_from_sender(sender)
        
        # Get memory for this conversation
        memory = get_mongodb_memory(user_email, thread_id)
        if not memory:
            raise Exception("Failed to create memory for conversation")
        
        # Check if the thread has more than 8 messages
        if len(memory.chat_memory.messages) > 8:
            print(f"[INFO] Thread has {len(memory.chat_memory.messages)} messages, exceeding the limit of 8. Skipping processing.")
            return {
                'email': user_email,
                'thread_id': thread_id,
                'subject': subject,
                'response': "This conversation has exceeded the maximum number of allowed exchanges. Please start a new conversation or contact support directly for further assistance."
            }
        
        # Check if this is a new conversation
        is_new_conversation = len(memory.chat_memory.messages) == 0
        
        # If it's a new conversation, prepend the email address to the content
        if is_new_conversation:
            agent_input = f"{user_email} - Thread ID: {thread_id} - \"{cleaned_content}\""
            print(f"[INFO] New conversation detected, prepending email address to message")
        else:
            agent_input = cleaned_content
        
        # Update metadata fields individually to preserve other fields (like screenshot_drive_links)
        memory.update_metadata_field('subject', subject)
        memory.update_metadata_field('sender_name', sender)
        memory.update_metadata_field('last_updated', datetime.now().isoformat())
        memory.update_metadata_field('status', 'In Progress')
        
        # Process the email content with the shared agent
        try:
            result = process_with_agent(agent_input, memory)
            response = result.get("output", "")
            
            # Check if agent determined no response is needed
            if response.strip() == "NO_RESPONSE_NEEDED":
                print(f"[INFO] Agent determined no response needed for this message")
                memory.update_metadata_field('status', 'Ignored')
                return None
            
            # Inject thread_id into log_user_details calls if not already present
            if "log_user_details" in response and thread_id:
                if f"thread_id='{thread_id}'" not in response and f'thread_id="{thread_id}"' not in response:
                    # Use regex to add thread_id parameter
                    pattern = r"log_user_details\s*\("
                    modified_response = re.sub(
                        pattern,
                        f"log_user_details(thread_id='{thread_id}', ",
                        response
                    )
                    response = modified_response
            
        except Exception as e:
            print(f"[ERROR] Error processing with agent: {str(e)}")
            traceback.print_exc()
            response = "I'm currently experiencing technical difficulties. Our support team has been notified and will get back to you shortly."
        
        # Update metadata fields individually for response status to preserve other fields
        memory.update_metadata_field('last_response', response[:100] + "..." if len(response) > 100 else response)
        memory.update_metadata_field('last_response_time', datetime.now().isoformat())
        memory.update_metadata_field('status', 'Responded')
        
        # Prepare result before cleanup
        result = {
            'email': user_email,
            'thread_id': thread_id,
            'subject': subject,
            'response': response
        }
        
        # Clear large variables to free memory
        cleaned_content = None
        agent_input = None
        memory = None
        
        # Force garbage collection
        gc.collect()
        
        return result
        
    except Exception as e:
        print(f"[ERROR] Error processing email: {str(e)}")
        traceback.print_exc()
        
        # Try to extract minimal info for error reporting
        user_email = extract_email_from_sender(email_data.get('sender', '')) if 'sender' in email_data else "unknown@example.com"
        thread_id = email_data.get('thread_id', email_data.get('id', 'unknown-id'))
        subject = email_data.get('subject', 'Error processing email')
        
        error_response = f"I encountered an error while processing your email. Please try again or contact our support team directly."
        
        # Perform cleanup even when there's an error
        gc.collect()
        
        return {
            'email': user_email,
            'thread_id': thread_id,
            'subject': subject,
            'response': error_response
        }
    
def email_monitor_loop():
    """Monitor emails and process them using the shared agent with MongoDB memory."""
    try:
        # Get Gmail service
        service = get_gmail_service()
        
        # Preload the shared agent to avoid initialization delay on first request
        get_shared_agent()
        #log_message("Shared agent initialized successfully")
        
        # Read system prompt
        try:
            with open('prompts.txt', 'r') as file:
                system_prompt = file.read()
        except FileNotFoundError:
            log_error("Warning: prompts.txt file not found! Using default prompt.")
            system_prompt = "You are a helpful assistant for an educational app's customer service."
        
        # Record start time 
        start_time = JUNE_20_START_TIME  # May 20th, 2025 at 00:00:00 UTC
        #log_message(f"Starting email monitor at {datetime.datetime.now().isoformat()}")
        #log_message(f"Looking for emails after {datetime.datetime.fromtimestamp(start_time)}")
        print(f"\nMonitoring emails sent to {IMPERSONATED_USER}")
        print("Press Ctrl+C to stop\n")
        
        # Track processed message IDs to avoid duplicates
        processed_messages = set()
        
        # Main loop
        while True:
            try:
                # Fetch new emails with mark_as_read=True
                emails = fetch_emails_after_time(service, start_time, mark_as_read=True)
                
                if emails:
                    # Filter out any messages we've already processed this session
                    new_emails = [email for email in emails if email['id'] not in processed_messages]
                    
                    if new_emails:
                        #log_message(f"Processing {len(new_emails)} new emails")
                        
                        # Process each email
                        for email in new_emails:
                            try:
                                # Add to processed set
                                processed_messages.add(email['id'])
                                
                                # Process the email
                                result = process_email(email, system_prompt)
                                
                                # Send the response only if result is not None (response needed)
                                if result:
                                    #log_message(f"Generated response for email from {result['email']}")
                                    
                                    # Send response (certificates are handled within the function)
                                    reply_result = send_email_reply(
                                        service=service,
                                        to=result['email'],
                                        subject=result['subject'],
                                        body_text=result['response'],
                                        thread_id=result['thread_id']
                                    )
                                    
                                    if reply_result:
                                        log_message(f"Sent response to {result['email']} in thread {result['thread_id']}")
                                    else:
                                        log_error(f"Failed to send response to {result['email']}")
                                else:
                                    log_message(f"No response needed for message - skipping reply")
                                
                            except Exception as e:
                                log_error(f"Error handling email {email.get('id')}: {str(e)}")
                                traceback.print_exc()
                    else:
                        log_message("No new unprocessed emails found")
                else:
                    log_message("No new emails found")
                
                # Wait before checking again
                wait_time = 30  # Check every 30 seconds
                #log_message(f"Waiting {wait_time} seconds before checking again...")
                time.sleep(wait_time)
                
            except KeyboardInterrupt:
                #log_message("Keyboard interrupt detected. Exiting...")
                return 0
                
            except Exception as e:
                log_error(f"Error in monitoring loop: {str(e)}")
                traceback.print_exc()
                #log_message("Waiting 30 seconds before retrying...")
                time.sleep(30)  # Wait 30 seconds before retry
                
    except Exception as e:
        log_error(f"Fatal error in email monitor: {str(e)}")
        traceback.print_exc()
        return 1


def test_gmail_connection():
    """Test the Gmail connection and print some profile info."""
    try:
        service = get_gmail_service()
        profile = service.users().getProfile(userId='me').execute()
        
        print("\n" + "="*60)
        print("GMAIL CONNECTION TEST")
        print("-"*60)
        print(f"Connected as: {profile.get('emailAddress')}")
        print(f"Messages Total: {profile.get('messagesTotal')}")
        print(f"Threads Total: {profile.get('threadsTotal')}")
        print("="*60 + "\n")
        
        return True
    except Exception as e:
        log_error(f"Gmail connection test failed: {str(e)}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    #log_message("Starting Gmail-MongoDB Integration Service with Shared Agent")
    if test_gmail_connection():
        #log_message("Starting email monitor loop")
        sys.exit(email_monitor_loop())
    else:
        log_error("Gmail connection test failed. Please")