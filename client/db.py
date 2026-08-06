import sqlite3
import hashlib
import json
from typing import Optional, List, Dict, Any
from pathlib import Path


class NYXDatabase:
    """Database for NYX client"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._init_db()
    
    def _init_db(self):
        """Initialize database connection and schema"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        
        # Create tables
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS identities (
                id TEXT PRIMARY KEY,
                private_key BLOB NOT NULL,
                public_key BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS contacts (
                identity_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                public_key TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                participants TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_messages_conversation 
            ON messages(conversation_id);
            
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp 
            ON messages(timestamp);
        """)
        self.conn.commit()
    
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a SQL query"""
        return self.conn.execute(sql, params)
    
    def load_identity(self) -> Optional[Dict[str, Any]]:
        """Load identity from database"""
        cursor = self.conn.execute(
            "SELECT id, private_key, public_key FROM identities LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            return {
                'id': row['id'],
                'private_key': row['private_key'],
                'public_key': row['public_key']
            }
        return None
    
    def save_identity(self, identity_id: str, private_key: bytes, public_key: bytes):
        """Save identity to database"""
        self.conn.execute(
            "INSERT OR REPLACE INTO identities (id, private_key, public_key) VALUES (?, ?, ?)",
            (identity_id, private_key, public_key)
        )
        self.conn.commit()
    
    def list_contacts(self) -> List[Dict[str, Any]]:
        """List all contacts"""
        cursor = self.conn.execute(
            "SELECT identity_id, name, public_key, added_at FROM contacts ORDER BY name"
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def save_contact(self, name: str, identity_id: str, public_key: str = ""):
        """Save a contact"""
        self.conn.execute(
            "INSERT OR REPLACE INTO contacts (identity_id, name, public_key) VALUES (?, ?, ?)",
            (identity_id, name, public_key)
        )
        self.conn.commit()
    
    def get_contact(self, identity_id: str) -> Optional[Dict[str, Any]]:
        """Get a contact by identity ID"""
        cursor = self.conn.execute(
            "SELECT identity_id, name, public_key FROM contacts WHERE identity_id = ?",
            (identity_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def list_conversations(self) -> List[Dict[str, Any]]:
        """List all conversations"""
        cursor = self.conn.execute("""
            SELECT 
                conversation_id,
                participants,
                created_at,
                (SELECT COUNT(*) FROM messages WHERE messages.conversation_id = conversations.conversation_id) as message_count
            FROM conversations
            ORDER BY created_at DESC
        """)
        
        result = []
        for row in cursor.fetchall():
            participants = json.loads(row['participants'])
            result.append({
                'conversation_id': row['conversation_id'],
                'participants': participants,
                'participant_count': len(participants),
                'message_count': row['message_count'],
                'created_at': row['created_at']
            })
        return result
    
    def ensure_conversation(self, participants: List[str]) -> str:
        """Ensure a conversation exists, create if not"""
        # Sort participants for consistent conversation ID
        sorted_participants = sorted(participants)
        
        # Generate conversation ID from participants
        conv_hash = hashlib.sha256(
            json.dumps(sorted_participants).encode()
        ).hexdigest()[:16]
        conversation_id = f"conv_{conv_hash}"
        
        # Check if exists
        cursor = self.conn.execute(
            "SELECT conversation_id FROM conversations WHERE conversation_id = ?",
            (conversation_id,)
        )
        if cursor.fetchone():
            return conversation_id
        
        # Create new conversation
        self.conn.execute(
            "INSERT INTO conversations (conversation_id, participants) VALUES (?, ?)",
            (conversation_id, json.dumps(sorted_participants))
        )
        self.conn.commit()
        return conversation_id
    
    def get_messages(self, conversation_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get messages for a conversation"""
        cursor = self.conn.execute("""
            SELECT id, conversation_id, from_id, to_id, content, timestamp
            FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (conversation_id, limit))
        
        messages = [dict(row) for row in cursor.fetchall()]
        return list(reversed(messages))  # Return in chronological order
    
    def save_message(self, conversation_id: str, from_id: str, to_id: str, content: str):
        """Save a message"""
        self.conn.execute("""
            INSERT INTO messages (conversation_id, from_id, to_id, content)
            VALUES (?, ?, ?, ?)
        """, (conversation_id, from_id, to_id, content))
        self.conn.commit()
    
    def get_unread_count(self, identity_id: str) -> int:
        """Get count of unread messages"""
        # This is a placeholder - would need a read_status table in production
        return 0
    
    def commit(self):
        """Commit current transaction"""
        if self.conn:
            self.conn.commit()
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
