#!/usr/bin/env python3
# agent_main_with_mongodb.py - Updated with MongoDB memory integration and shared agent
# CRM agent with logging functionality and MongoDB memory support
import gc
import os
import requests
from urllib.parse import quote_plus
import json
import argparse
import datetime
import hashlib
import uuid
import traceback
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.memory import ConversationBufferMemory
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain.tools import StructuredTool
from sheets_service import log_certificate_issue, log_payment_issue, log_subscription_issue, log_refund_request, log_technical_issue, log_account_deletion, log_to_sheet
import time

# Import MongoDB memory system
from mongodb_memory import MongoDBMemory, MongoDBChatMessageHistory

# Load environment variables
load_dotenv()

# MongoDB configuration
MONGO_HOST = os.getenv("MONGODB_HOST", "localhost:27017")
MONGO_USER = os.getenv("MONGODB_USER")
MONGO_PASS = os.getenv("MONGODB_PASS")
DB_NAME = os.getenv("MONGODB_DB_NAME", "xseries-crm")
CONVERSATIONS_COLLECTION = os.getenv("MONGODB_CONVERSATIONS_COLLECTION", "conversations")

# Use MONGODB_URI from .env if present, otherwise build it
MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    # Encode username and password safely
    encoded_user = quote_plus(MONGO_USER) if MONGO_USER else ""
    encoded_pass = quote_plus(MONGO_PASS) if MONGO_PASS else ""

    # Build MongoDB URI from environment variables if available
    if MONGO_USER and MONGO_PASS:
        # Authenticate against the 'admin' database, which is common practice
        MONGODB_URI = f"mongodb://{encoded_user}:{encoded_pass}@{MONGO_HOST}/?authSource=admin"
    else:
        MONGODB_URI = f"mongodb://{MONGO_HOST}/"

# Get OpenAI API key from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def clear_agent_memory():
    """Clear any accumulated memory in the shared agent without recreating it"""
    global SHARED_AGENT
    
    if SHARED_AGENT is not None:
        # Force garbage collection
        gc.collect()
        
        log_message("Cleared agent memory after response")
        return True
    
    return False

def log_message(message):
    """Simple logging function"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] INFO: {message}")

def log_error(message):
    """Simple error logging function"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] ERROR: {message}")

def print_order_details(orderid: str, emailid: str) -> str:
    """Print order details for a customer."""
    print("\n[ORDER DETAILS TOOL CALLED]")
    print("--------------")
    print(f"Order ID: {orderid}")
    print(f"Customer Email: {emailid}")
    print(f"Status: Shipped")
    print(f"Date: March 10, 2025")
    print(f"Items:")
    print(f"- Educational Course: Python Programming 101")
    print(f"- Educational Materials: Course Handbook")
    print(f"Total: $199.99")
    print(f"Estimated Delivery: March 15, 2025")
    
    return f"I've retrieved the order details for order ID {orderid}. The order is currently shipped and should be delivered by March 15, 2025. The order contains the Python Programming 101 course and course handbook. Total: $199.99."

def generate_certificate(user_name: str, course_name: str) -> str:
    """Generate a certificate for a user by calling the certificate API."""
    try:
        # Generate a user ID hash based on the name for demo purposes
        user_id = hashlib.md5(user_name.encode()).hexdigest()
        
        # Get today's date in the required format
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # Create directories for certificates if they don't exist
        certificate_path = os.getenv("CERTIFICATE_PATH", "./certificates")
        os.makedirs(certificate_path, exist_ok=True)
        
        # Create a filename with timestamp to ensure uniqueness
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{certificate_path}/certificate_{user_name.replace(' ', '_')}_{course_name.replace(' ', '_')}_{timestamp}.pdf"
        
        # Prepare the API request
        url = "https://certificationportal-h72gj5jcwq-uc.a.run.app/certificate/getfile/PH"
        headers = {'content-type': 'application/json'}
        payload = {
            "today": today,
            "name": user_name,
            "userId": user_id,
            "subject": course_name,
            "sample": False,
            "excellence": True,
            "preExcellence": False,
            "type": "pdf",
            "finalCertificate": True
        }
        
        print(f"\n[CERTIFICATE TOOL CALLED]")
        print(f"Generating certificate for {user_name}, course: {course_name}...")
        
        # Make the actual API call
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            stream=True
        )
        
        # Check if the request was successful
        if response.status_code == 200:
            # Save the certificate to a file
            with open(filename, 'wb') as f:
                f.write(response.content)
            
            print(f"Certificate generated successfully and saved as: {filename}")
            
            return f"Certificate generation successful. A new certificate for '{user_name}' for the course '{course_name}' has been generated and saved as '{filename}'. The certificate is ready for download and has also been emailed to the user's registered email address."
        else:
            error_msg = f"API returned status code {response.status_code}"
            print(f"Error: {error_msg}")
            return f"Certificate generation failed: {error_msg}. Please try again later or contact support."
        
    except Exception as e:
        print(f"Error generating certificate: {str(e)}")
        return f"Certificate generation failed with error: {str(e)}. Please ask the user to try again later or contact technical support."

def generate_certificates(user_name: str, course_names: list) -> str:
    """
    Generate certificates for multiple courses.
    
    Parameters:
    - user_name: The name to appear on the certificates
    - course_names: A list of course names for which to generate certificates
    
    Returns:
    - A message summarizing the results
    """
    if not course_names:
        return "No courses specified for certificate generation."
    
    # Track successful and failed generations
    successes = []
    failures = []
    filenames = []
    
    # Create directories for certificates if they don't exist
    certificate_path = os.getenv("CERTIFICATE_PATH", "./certificates")
    os.makedirs(certificate_path, exist_ok=True)
    
    # Generate a certificate for each course
    for course_name in course_names:
        try:
            # Generate a user ID hash based on the name for demo purposes
            user_id = hashlib.md5(f"{user_name}_{course_name}".encode()).hexdigest()
            
            # Get today's date in the required format
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # Create a filename with timestamp to ensure uniqueness
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{certificate_path}/certificate_{user_name.replace(' ', '_')}_{course_name.replace(' ', '_')}_{timestamp}.pdf"
            
            # Prepare the API request
            url = "https://certificationportal-h72gj5jcwq-uc.a.run.app/certificate/getfile/PH"
            headers = {'content-type': 'application/json'}
            payload = {
                "today": today,
                "name": user_name,
                "userId": user_id,
                "subject": course_name,
                "sample": False,
                "excellence": True,
                "type": "pdf",
                "finalCertificate": False
            }
            
            print(f"\n[CERTIFICATE TOOL CALLED]")
            print(f"Generating certificate for {user_name}, course: {course_name}...")
            
            # Make the actual API call
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                stream=True
            )
            
            # Check if the request was successful
            if response.status_code == 200:
                # Save the certificate to a file
                with open(filename, 'wb') as f:
                    f.write(response.content)
                
                print(f"Certificate generated successfully and saved as: {filename}")
                successes.append(course_name)
                filenames.append(filename)
            else:
                error_msg = f"API returned status code {response.status_code}"
                print(f"Error: {error_msg}")
                failures.append((course_name, error_msg))
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error generating certificate for {course_name}: {error_msg}")
            failures.append((course_name, error_msg))
    
    # Construct the response message
    if successes and not failures:
        return f"Certificate generation successful. {len(successes)} certificates for '{user_name}' have been generated for the following courses: {', '.join(successes)}. The certificates are ready for download and have also been emailed to your registered email address."
    elif successes and failures:
        failed_courses = [f[0] for f in failures]
        return f"Partial success. Certificates were generated for these courses: {', '.join(successes)}. However, we encountered issues with these courses: {', '.join(failed_courses)}. The successful certificates are ready for download and have been emailed to your registered email address."
    else:
        return f"Certificate generation failed for all courses. Please try again later or contact support."
    
def activate_premium(emailid: str, app_name: str) -> str:
    """Activate premium access for a user's account with specified app name."""
    try:
        print(f"\n[PREMIUM ACTIVATION TOOL CALLED]")
        print(f"Activating premium for email: {emailid} on app: {app_name}")
        
        # Calculate expiry time (current timestamp + 1 year in milliseconds)
        current_time_ms = int(time.time() * 1000)
        expiry_time_ms = current_time_ms + (365 * 24 * 60 * 60 * 1000)  # Roughly 1 year in ms
        
        # Prepare the API request with new endpoint
        url = "https://api-prod.programminghub.io/v5/api/auth/pro/add"
        headers = {
            'Content-Type': 'application/json'
        }
        
        payload = {
            "code_type": "ONETIME",
            "email": emailid,
            "expiry_time": expiry_time_ms,
            "promo_code": "VIKR0000"
        }
        
        print(f"Sending request to: {url}")
        print(f"Headers: {headers}")
        print(f"Payload: {json.dumps(payload)}")
        
        # Make the actual API call
        response = requests.post(
            url,
            headers=headers,
            json=payload
        )
        
        response_data = response.json()
        print(f"Response: {json.dumps(response_data)}")
        
        if response.status_code == 200:
            print(f"Premium activation successful for {emailid} on {app_name}")
            return f"Premium access has been successfully activated for {emailid} on {app_name}. The premium features will be available immediately, and the subscription is valid for 12 months."
        else:
            return f"Premium activation failed: {response_data.get('message', 'Unknown error')}. Please try again later."
        
    except requests.exceptions.RequestException as e:
        # Handle network-related errors
        error_message = f"Error connecting to the activation service: {str(e)}"
        print(error_message)
        return f"Premium activation failed: {error_message}. Please check your internet connection and try again later."
    except Exception as e:
        # Handle all other exceptions
        error_message = f"Error activating premium: {str(e)}"
        print(error_message)
        return f"Premium activation failed with error: {error_message}. Please try again later or contact technical support."

def log_user_details(issue_type, app_name, initial_message, new_name=None, course_name=None, 
                    email=None, order_id=None, device=None, os_version=None, app_version=None, 
                    thread_id=None, country=None, **kwargs):

    """
    Log user details to the appropriate sheets based on issue type.
    
    This is designed to be a drop-in replacement for your existing log_user_details function
    but with Google Sheets logging added.
    
    Parameters:
    - issue_type: Type of issue (e.g., "Certificate Issue", "Premium Access", "Order Inquiry")
    - app_name: Name of the app the user is using
    - initial_message: The first message the user sent
    - new_name: New name requested for the certificate (for Certificate Issue)
    - course_name: Name of the course (for Certificate Issue)
    - email: User's email address
    - order_id: Order ID for premium/subscription issues
    - **kwargs: Additional details that might be provided
    
    Returns:
    - Confirmation message
    """
    # First, log to the console as before
    print("\n[LOGGING TOOL CALLED]")
    print("--------------")
    print(f"Issue Type: {issue_type}")
    print(f"App Name: {app_name}")
    print(f"thread_id: {thread_id}")
    print(f"Initial Message: {initial_message}")
    
    # Set a default status
    status = kwargs.get('status', 'Open')
    
    # Set default email
    email = email if email else 'Not provided'
    
    # Log details specific to issue type
    if issue_type == "Certificate Issue":
        print(f"Course Name: {course_name if course_name else 'Not provided'}")
        print(f"New Name: {new_name if new_name else 'Not provided'}")
        
        # Log to Google Sheets
        log_certificate_issue(
            app_name=app_name,
            email=email,
            course=course_name if course_name else 'Not provided', 
            new_name=new_name if new_name else 'Not provided',
            initial_message=initial_message,
            status=status
        )
        
    elif issue_type in ["Premium Access", "Subscription Issue"]:
        print(f"Email: {email}")
        print(f"Order ID: {order_id if order_id else 'Not provided'}")
        
        # Log to Google Sheets - Subscription Issues
        log_subscription_issue(
            app_name=app_name,
            email=email,
            order_id=order_id if order_id else 'Not provided',
            initial_message=initial_message,
            status=status
        )
        
    elif issue_type == "Refund Request" or issue_type == "Refund":
        print(f"Email: {email}")
        print(f"Order ID: {order_id if order_id else 'Not provided'}")
        
        # Log to Google Sheets - Refund
        log_refund_request(
            app_name=app_name,
            email=email,
            order_id=order_id if order_id else 'Not provided',
            initial_message=initial_message,
            status=status
        )
        
    elif issue_type == "Technical Issue":
        
        print(f"Device: {device}")
        print(f"OS Version: {os_version}")
        print(f"App Version: {app_version}")
        
        # Log to Google Sheets
        log_technical_issue(
            app_name=app_name,
            email=email,
            issue_description=initial_message,
            device=device,
            os_version=os_version,
            app_version=app_version,
            status=status,
            thread_id=thread_id  # Pass thread_id for screenshot handling
        )
    elif issue_type == "Payment Issue":
        print(f"Email: {email}")
        print(f"App Name: {app_name}")
        
        # Log to Google Sheets
        log_payment_issue(
            app_name=app_name,
            email=email,
            initial_message=initial_message,
            country=country if country else 'Not provided',
            status=status
        )

        
    elif issue_type == "Account Deletion":
        print(f"Email: {email}")
        
        # Log to Google Sheets
        log_account_deletion(
            app_name=app_name,
            email=email,
            initial_message=initial_message,
            status=status
        )
        
    elif issue_type == "Order Inquiry":
        print(f"Order ID: {order_id if order_id else 'Not provided'}")
        print(f"Email: {email}")
        
        # Log as a general entry to All-Logs only
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_to_sheet("All-Logs", [
            timestamp,
            "Order Inquiry",
            app_name,
            email,
            initial_message,
            status
        ])
    
    # For any other issue type, just log to All-Logs
    else:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_to_sheet("All-Logs", [
            timestamp,
            issue_type,
            app_name,
            email,
            initial_message,
            status
        ])
    
    # Additional details that might be provided
    for key, value in kwargs.items():
        if key not in ['course_name', 'new_name', 'email', 'order_id', 'status', 'device', 'os_version', 'app_version']:
            print(f"{key.replace('_', ' ').title()}: {value}")
    
    print("User details logged successfully.")
    print(f"Issue Type Logged: {issue_type}")
    
    return f"User details for {issue_type} have been logged successfully."

# Function to format and print replies to the user
def reply_to_user(message: str) -> None:
    """Format and print a reply to the user."""
    print(f"\n[AGENT REPLY]: {message}\n")

# Global shared agent instance
SHARED_AGENT = None
SHARED_TOOLS = None

def create_shared_agent(openai_api_key=None):
    """
    Create a shared agent instance that can be reused across different user conversations.
    This agent doesn't have memory attached - memory will be provided for each conversation.
    
    Returns:
        The initialized agent without memory
    """
    # Set your OpenAI API key from environment variables
    if not openai_api_key:
        openai_api_key = OPENAI_API_KEY
    print(f"API key loaded: {'Key present' if openai_api_key else 'No key found'}")
    
    # Initialize the language model
    llm = ChatOpenAI(temperature=0.7, model="gpt-4o-mini-2024-07-18", openai_api_key=openai_api_key, verbose=True)
    
    # Create tools from the functions
    order_details_tool = StructuredTool.from_function(
        func=print_order_details,
        name="print_order_details",
        description="Print order details for a customer based on their order ID and email ID"
    )
    
    certificate_tool = StructuredTool.from_function(
        func=generate_certificate,
        name="generate_certificate",
        description="Generate a certificate for a user by providing their name and the course name"
    )
    
    premium_tool = StructuredTool.from_function(
        func=activate_premium,
        name="activate_premium",
        description="Activate premium access for a user account using their email ID and app name"
    )
    
    logging_tool = StructuredTool.from_function(
        func=log_user_details,
        name="log_user_details",
        description="Log user details for tracking and analytics. Must be called before generating certificates or activating premium."
    )

    multi_certificate_tool = StructuredTool.from_function(
        func=generate_certificates,
        name="generate_certificates",
        description="Generate certificates for multiple courses at once by providing the user's name and a list of course names"
    )
    
    # Convert the tools to OpenAI's format
    tools = [order_details_tool, certificate_tool, premium_tool, logging_tool, multi_certificate_tool]
    
    # Read the system prompt from file
    try:
        with open('prompts.txt', 'r') as file:
            system_prompt = file.read()
    except FileNotFoundError:
        log_error("Error: prompts.txt file not found!")
        system_prompt = "You are a helpful assistant for an educational app's customer service."
    except Exception as e:
        log_error(f"Error reading prompts.txt: {str(e)}")
        system_prompt = "You are a helpful assistant for an educational app's customer service."
    
    # Create a prompt template with clear instructions
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad")
    ])
    
    # Create the agent - pass the original tools, not the converted ones
    agent = create_openai_functions_agent(llm, tools, prompt)
    
    return agent, tools

def get_shared_agent():
    """Get or create the shared agent instance"""
    global SHARED_AGENT, SHARED_TOOLS
    if SHARED_AGENT is None:
        SHARED_AGENT, SHARED_TOOLS = create_shared_agent()
    return SHARED_AGENT, SHARED_TOOLS

def process_with_agent(input_text, memory):
    """
    Process input with the shared agent using the provided memory.
    
    Args:
        input_text: The text input to process
        memory: The memory object for this conversation
        
    Returns:
        The agent's response
    """
    agent, tools = get_shared_agent()
    print("printing memory in process_with_agent")
    print(memory)
    
    # Print the chat history specifically
    print("\n=== CHAT HISTORY START ===")
    if hasattr(memory, 'chat_memory') and hasattr(memory.chat_memory, 'messages'):
        for i, message in enumerate(memory.chat_memory.messages):
            print(f"Message {i+1} ({message.type}):")
            print(f"  Content: {message.content}")
            print()
    else:
        print("No chat history found or not in expected format")
    print("=== CHAT HISTORY END ===\n")
    
    # You can also print the chat history as it will be formatted in the prompt
    #print("\n=== FORMATTED CHAT HISTORY START ===")
   # if hasattr(memory, 'load_memory_variables'):
      #  chat_history = memory.load_memory_variables({})
    #    print(chat_history.get('chat_history', 'No chat history found'))
   # else:
     #   print("Memory object doesn't have load_memory_variables method")
    #print("=== FORMATTED CHAT HISTORY END ===\n")
    
    # Create the agent executor with the provided memory
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=6
    )
   # print("printing agent_executor")
   # print(agent_executor)
    
    # Process the query with the agent
    result = agent_executor.invoke({"input": input_text})
    return result
# For backward compatibility
def create_agent(use_mongodb=False, user_email=None, thread_id=None):
    """
    Create an agent with either in-memory or MongoDB-based memory.
    
    Args:
        use_mongodb: Whether to use MongoDB for memory persistence
        user_email: User's email (required for MongoDB memory)
        thread_id: Thread ID (required for MongoDB memory)
        
    Returns:
        The initialized agent executor
    """
    # Initialize memory based on parameters
    try:
        if use_mongodb and user_email and thread_id:
            # Use MongoDB-based memory
            memory = MongoDBMemory(
                connection_string=MONGODB_URI,
                db_name=DB_NAME,
                collection_name=CONVERSATIONS_COLLECTION,
                user_email=user_email,
                thread_id=thread_id,
                memory_key="chat_history",
                return_messages=True
            )
            #log_message(f"Using MongoDB memory with thread_id: {thread_id}")
        else:
            # Use in-memory ConversationBufferMemory
            memory = ConversationBufferMemory(return_messages=True, memory_key="chat_history")
            #log_message("Using in-memory conversation buffer")
    except Exception as e:
        log_error(f"Error creating memory: {str(e)}")
        traceback.print_exc()
        # Fallback to in-memory
        memory = ConversationBufferMemory(return_messages=True, memory_key="chat_history")
        #log_message("Falling back to in-memory conversation buffer due to error")
    
    # Get the shared agent
    agent, tools = get_shared_agent()
    
    # Create the agent executor with the memory
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=6
    )
    
    return agent_executor

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Educational App CRM Agent")
    parser.add_argument("--mongodb", action="store_true", help="Use MongoDB for memory persistence")
    parser.add_argument("--email", help="User email (required for MongoDB memory)")
    parser.add_argument("--thread-id", help="Thread ID (required for MongoDB memory)")
    args = parser.parse_args()
    
    # Check if MongoDB is requested but email/thread ID are missing
    if args.mongodb and (not args.email or not args.thread_id):
        log_error("When using MongoDB, both --email and --thread-id are required.")
        parser.print_help()
        return 1
    
    # Generate a thread ID if not provided
    thread_id = args.thread_id
    if args.mongodb and not thread_id:
        thread_id = f"console_{int(datetime.datetime.now().timestamp())}_{args.email}"
        #log_message(f"Generated thread ID: {thread_id}")
    
    # Create the agent with the specified memory type
    agent_executor = create_agent(
        use_mongodb=args.mongodb,
        user_email=args.email,
        thread_id=thread_id
    )
    
    # Print startup message
    print("Educational App CRM Agent initialized\n")
    if args.mongodb:
        print(f"Using MongoDB memory persistence")
        print(f"User Email: {args.email}")
        print(f"Thread ID: {thread_id}")
    else:
        print("Using in-memory conversation (not persisted)")
    
    print("\nExample flows:")
    print("1. Order Details Flow:")
    print("   User: 'Hi! I want to know my order details.'")
    print("   Agent: Asks for order ID and email")
    print("   User: Provides order ID and email")
    print("   Agent: Logs details, then uses print_order_details tool and responds")
    print("2. Certificate Flow:")
    print("   User: 'I need to change the name on my certificate.'")
    print("   Agent: Asks for new name, app name, and course name")
    print("   User: Provides the requested information")
    print("   Agent: Logs details, then uses generate_certificate tool and responds")
    print("3. Premium Activation Flow:")
    print("   User: 'I paid for premium but I'm still a free user.'")
    print("   Agent: Asks for order ID, email, and app name")
    print("   User: Provides the requested information")
    print("   Agent: Logs details, then uses activate_premium tool and responds")
    print("\n--- Begin Interaction ---\n")
            
    # Store the first message from the user for logging
    first_message = None
    
    # Main interaction loop
    while True:
        query = input("User: ")
        if query.lower() in ['exit', 'quit', 'bye']:
            reply_to_user("Thank you for contacting our support. Have a great day!")
            break
        
        # Save the first message for logging purposes
        if first_message is None:
            first_message = query
        
        try:
            # Process the query with the agent
            result = agent_executor.invoke({"input": query})
            
            # Use the reply_to_user function to display the agent's response
            if "output" in result:
                reply_to_user(result["output"])
                
        except Exception as e:
            log_error(f"Error processing query: {str(e)}")
            traceback.print_exc()
            reply_to_user(f"Sorry, I encountered an error: {str(e)}")

if __name__ == "__main__":
    main()