from pymongo import MongoClient
from dotenv import load_dotenv
import os
from langchain.memory import ConversationBufferMemory
from langchain.schema import BaseChatMessageHistory
from langchain.schema.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from html import unescape
import re
from urllib.parse import quote_plus
from typing import List, Any, Optional, Dict
from datetime import datetime, timezone


# Load environment variables
load_dotenv()

# Get the MongoDB URI from the environment
MONGODB_URI = os.getenv('MONGODB_URI')

class MongoDBChatMessageHistory(BaseChatMessageHistory):
    """Chat message history stored in MongoDB with a simplified document structure."""

    def __init__(
        self,
        db_name: str,
        collection_name: str,
        user_email: str,
        thread_id: str,
    ):
        self.connection_string = MONGODB_URI
        self.db_name = db_name
        self.collection_name = collection_name
        self.user_email = user_email
        self.thread_id = thread_id

        self.client = MongoClient(self.connection_string)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]

    def add_message(self, message: BaseMessage) -> None:
        """Add a message to the store, with HTML cleaning."""
        if message.type == "human" and message.content and isinstance(message.content, str):
            text = unescape(message.content)
            cleaned_content = re.sub(r'<[^>]+>', '', text)
            cleaned_content = re.sub(r'\s+', ' ', cleaned_content).strip()

            if "EXTRACTED IMAGE CONTENT" in message.content and "EXTRACTED IMAGE CONTENT" not in cleaned_content:
                extracted_content_blocks = re.findall(r'EXTRACTED IMAGE CONTENT.*?(?=\n\n|\Z)', message.content, re.DOTALL)
                if extracted_content_blocks:
                    cleaned_content += "\n\n" + "\n\n".join(extracted_content_blocks)

            if message.content != cleaned_content:
                if message.type == "human":
                    message = HumanMessage(content=cleaned_content)

        message_entry = {
            "role": message.type,
            "content": message.content
        }

        now = datetime.now(timezone.utc)

        conversation = self.collection.find_one({
            "thread_id": self.thread_id
        })

        if conversation:
            self.collection.update_one(
                {"thread_id": self.thread_id},
                {
                    "$push": {"chat": message_entry},
                    "$set": {"last_updated": now}
                }
            )
        else:
            conversation_doc = {
                "user_email": self.user_email,
                "thread_id": self.thread_id,
                "chat": [message_entry],
                "metadata": {},
                "created_at": now,
                "last_updated": now
            }
            self.collection.insert_one(conversation_doc)

    def clear(self) -> None:
        """Clear conversation history for this thread."""
        self.collection.update_one(
            {"thread_id": self.thread_id},
            {"$set": {"chat": []}}
        )

    @property
    def messages(self) -> List[BaseMessage]:
        """Retrieve all messages from the store."""
        conversation = self.collection.find_one({
            "thread_id": self.thread_id
        })

        if not conversation or "chat" not in conversation:
            return []

        result = []
        for entry in conversation["chat"]:
            if entry["role"] == "human":
                result.append(HumanMessage(content=entry["content"]))
            elif entry["role"] == "ai":
                result.append(AIMessage(content=entry["content"]))
            elif entry["role"] == "system":
                result.append(SystemMessage(content=entry["content"]))

        return result
    
    def update_metadata_field(self, field: str, value: Any) -> None:
        """Update a specific metadata field without replacing the entire metadata object."""
        self.collection.update_one(
            {"thread_id": self.thread_id},
            {
                "$set": {
                    f"metadata.{field}": value,
                    "last_updated": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )
        
    def update_metadata(self, metadata: Dict[str, Any]) -> None:
        """Update conversation metadata."""
        self.collection.update_one(
            {"thread_id": self.thread_id},
            {
                "$set": {
                    "metadata": metadata,
                    "last_updated": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )


class MongoDBMemory(ConversationBufferMemory):
    """ConversationBufferMemory implementation using MongoDB for storage."""

    def __init__(
        self,
        db_name: str,
        collection_name: str,
        user_email: str,
        thread_id: str,
        memory_key: str = "chat_history",
        return_messages: bool = True,
        output_key: Optional[str] = None,
        input_key: Optional[str] = None,
        human_prefix: str = "Human",
        ai_prefix: str = "AI",
    ):
        message_history = MongoDBChatMessageHistory(
            db_name=db_name,
            collection_name=collection_name,
            user_email=user_email,
            thread_id=thread_id
        )

        super().__init__(
            chat_memory=message_history,
            memory_key=memory_key,
            return_messages=return_messages,
            output_key=output_key,
            input_key=input_key,
            human_prefix=human_prefix,
            ai_prefix=ai_prefix,
        )

    def update_metadata(self, metadata: Dict[str, Any]) -> None:
        """Update metadata for the current conversation."""
        if isinstance(self.chat_memory, MongoDBChatMessageHistory):
            self.chat_memory.update_metadata(metadata)
            
    def update_metadata_field(self, field: str, value: Any) -> None:
        """Update a specific field in metadata."""
        if isinstance(self.chat_memory, MongoDBChatMessageHistory):
            self.chat_memory.update_metadata_field(field, value)

    @staticmethod
    def get_thread(
        connection_string: str,
        db_name: str,
        collection_name: str,
        thread_id: str
    ) -> Dict[str, Any]:
        client = MongoClient(connection_string)
        db = client[db_name]
        collection = db[collection_name]

        thread = collection.find_one(
            {"thread_id": thread_id},
            {"_id": 0}
        )

        return thread
