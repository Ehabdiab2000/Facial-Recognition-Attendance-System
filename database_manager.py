# database_manager.py
import sqlite3
import config
import logging
import numpy as np
import io

logger = logging.getLogger(__name__)

# --- Numpy array adapter for SQLite ---
def adapt_array(arr):
    """Converts numpy array to BLOB."""
    out = io.BytesIO()
    np.save(out, arr)
    out.seek(0)
    return sqlite3.Binary(out.read())

def convert_array(text):
    """Converts BLOB back to numpy array."""
    out = io.BytesIO(text)
    out.seek(0)
    # Allow pickle due to np.save format, ensure security context if data source is untrusted
    return np.load(out, allow_pickle=True)

# Register the adapters
sqlite3.register_adapter(np.ndarray, adapt_array)
sqlite3.register_converter("ARRAY", convert_array)
# --- End Numpy array adapter ---


class DatabaseManager:
    def __init__(self, db_path=config.DATABASE_PATH):
        self.db_path = db_path
        self._create_tables()

    def _get_connection(self):
        # Use detect_types to enable the custom converters
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row # Return rows as dict-like objects
        return conn

    def _create_tables(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # Users table: Store ID, name, details, and face encoding (as BLOB)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    details TEXT,
                    encoding ARRAY NOT NULL, -- Custom type using converter
                    card_number TEXT UNIQUE,  -- New field for Wiegand card ID
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Transactions table: Log attendance records
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending', -- pending, sent, failed
                    method TEXT, -- New field for transaction method (face, card, manual)
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            # Add 'method' column to transactions table if it doesn't exist (for schema migration)
            try:
                cursor.execute("ALTER TABLE transactions ADD COLUMN method TEXT")
                logger.info("Added 'method' column to transactions table.")
            except sqlite3.OperationalError as e:
                if 'duplicate column name' in str(e):
                    pass # Column already exists, ignore
                else:
                    raise # Re-raise other operational errors

            conn.commit()
            logger.info("Database tables checked/created successfully.")
        except sqlite3.Error as e:
            logger.error(f"Database table creation error: {e}")
            conn.rollback()
        finally:
            conn.close()

    def add_user(self, name, details, encoding, card_number=None): # Added card_number
        conn = self._get_connection()
        cursor = conn.cursor()
        # Ensure card_number is None if empty string or whitespace, to allow NULL in DB for UNIQUE constraint
        card_number_to_db = card_number if card_number and card_number.strip() else None
        try:
            cursor.execute("INSERT INTO users (name, details, encoding, card_number) VALUES (?, ?, ?, ?)",
                           (name, details, encoding, card_number_to_db))
            conn.commit()
            user_id = cursor.lastrowid
            logger.info(f"User '{name}' (Card: {card_number_to_db}) added successfully with ID: {user_id}.")
            return user_id
        except sqlite3.IntegrityError as e: # Catch UNIQUE constraint violation for card_number
            logger.error(f"Failed to add user '{name}': {e}. Card number '{card_number_to_db}' might already exist.")
            conn.rollback()
            return None
        except sqlite3.Error as e:
            logger.error(f"Failed to add user '{name}': {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def get_all_users(self): # Fetch card_number too
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, name, details, encoding, card_number FROM users") # Added card_number
            users = cursor.fetchall()
            return users
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch users: {e}")
            return []
        finally:
            conn.close()

    def get_user_by_id(self, user_id): # Useful for UserManagementDialog
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, name, details, encoding, card_number FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone() # Returns a sqlite3.Row object or None
            return user
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch user by ID {user_id}: {e}")
            return None
        finally:
            conn.close()

    def add_transaction(self, user_id, method="unknown"):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO transactions (user_id, status, method) VALUES (?, ?, ?)",
                           (user_id, 'pending', method))
            conn.commit()
            transaction_id = cursor.lastrowid
            logger.info(f"Transaction logged for user ID {user_id}. Transaction ID: {transaction_id}")
            return transaction_id
        except sqlite3.Error as e:
            logger.error(f"Failed to log transaction for user ID {user_id}: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def get_pending_transactions(self, limit=10):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # Fetch transaction details along with user name for context
            cursor.execute("""
                SELECT t.id, t.user_id, t.timestamp, u.name
                FROM transactions t
                JOIN users u ON t.user_id = u.id
                WHERE t.status = 'pending'
                ORDER BY t.timestamp ASC
                LIMIT ?
            """, (limit,))
            transactions = cursor.fetchall()
            return transactions
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch pending transactions: {e}")
            return []
        finally:
            conn.close()

    def update_transaction_status(self, transaction_id, status):
        conn = self._get_connection()
        cursor = conn.cursor()
        allowed_statuses = ['sent', 'failed', 'pending']
        if status not in allowed_statuses:
            logger.error(f"Invalid status '{status}' provided for transaction update.")
            return False
        try:
            cursor.execute("UPDATE transactions SET status = ? WHERE id = ?",
                           (status, transaction_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Transaction {transaction_id} status updated to '{status}'.")
                return True
            else:
                logger.warning(f"Transaction {transaction_id} not found for status update.")
                return False
        except sqlite3.Error as e:
            logger.error(f"Failed to update status for transaction {transaction_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_user_details(self, user_id, name, details, card_number=None): # Added card_number
        """Updates the name, details, and card_number of an existing user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        card_number_to_db = card_number if card_number and card_number.strip() else None
        try:
            cursor.execute("UPDATE users SET name = ?, details = ?, card_number = ? WHERE id = ?",
                           (name, details, card_number_to_db, user_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"User ID {user_id} details (name, details, card) updated.")
                return True
            logger.warning(f"User ID {user_id} not found for detail update.")
            return False
        except sqlite3.IntegrityError as e:
            logger.error(f"Failed to update user {user_id}: Card number '{card_number_to_db}' may already be in use by another user. {e}")
            conn.rollback()
            return False
        except sqlite3.Error as e:
            logger.error(f"Failed to update user details for ID {user_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_user_by_card_number(self, card_number): # New method
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, name, details, encoding, card_number FROM users WHERE card_number = ?", (card_number,))
            user = cursor.fetchone() # Returns a sqlite3.Row object or None
            return user
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch user by card number {card_number}: {e}")
            return None
        finally:
            conn.close()
            
    def update_user_encoding(self, user_id, encoding):
        """Updates the face encoding of an existing user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET encoding = ? WHERE id = ?",
                           (encoding, user_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"User ID {user_id} face encoding updated successfully.")
                return True
            else:
                logger.warning(f"User ID {user_id} not found for encoding update.")
                return False
        except sqlite3.Error as e:
            logger.error(f"Failed to update encoding for user ID {user_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_user(self, user_id):
        """Deletes a user and their associated transactions."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # Optional: Delete associated transactions first (or set ON DELETE CASCADE)
            cursor.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
            logger.info(f"Deleted transactions for user ID {user_id}.")

            # Delete the user
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"User ID {user_id} deleted successfully.")
                return True
            else:
                logger.warning(f"User ID {user_id} not found for deletion.")
                # Rollback if user wasn't found but transactions might have been deleted?
                # Or commit anyway if deleting non-existent user's transactions is ok.
                # Let's commit as transactions might not exist anyway.
                return False
        except sqlite3.Error as e:
            logger.error(f"Failed to delete user ID {user_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()