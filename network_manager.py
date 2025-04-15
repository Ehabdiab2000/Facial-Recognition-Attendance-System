# network_manager.py
import requests
import threading
import queue
import time
import config
import logging
from database_manager import DatabaseManager # Import DatabaseManager class

logger = logging.getLogger(__name__)

class NetworkManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.upload_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        logger.info("NetworkManager initialized and worker thread started.")

    def queue_transaction(self, transaction_id):
        """Add a transaction ID to the queue for uploading."""
        if transaction_id:
            self.upload_queue.put(transaction_id)
            logger.debug(f"Transaction {transaction_id} queued for upload.")

    def _worker(self):
        """Worker thread process that attempts to send transactions."""
        while not self.stop_event.is_set():
            try:
                # Fetch a batch of pending transactions first
                pending = self.db_manager.get_pending_transactions(limit=5) # Process in batches
                if not pending:
                    # If no pending transactions in DB, check the queue (in case added very recently)
                    try:
                        # Check queue non-blockingly first
                        transaction_id = self.upload_queue.get_nowait()
                        logger.info(f"Processing transaction {transaction_id} directly from queue.")
                        # Fetch details for this specific transaction
                        # This might be less efficient than batching, reconsider if performance matters
                        temp_conn = self.db_manager._get_connection()
                        cursor = temp_conn.cursor()
                        cursor.execute("""
                            SELECT t.id, t.user_id, t.timestamp, u.name
                            FROM transactions t JOIN users u ON t.user_id = u.id
                            WHERE t.id = ? AND t.status = 'pending'
                         """, (transaction_id,))
                        single_txn = cursor.fetchone()
                        temp_conn.close()
                        if single_txn:
                           self._send_transaction(dict(single_txn)) # Send if found
                        else:
                           logger.warning(f"Transaction {transaction_id} from queue not found or not pending in DB.")
                           continue # Continue loop

                    except queue.Empty:
                        # Queue is empty and no pending in DB, wait before checking again
                        time.sleep(config.NETWORK_RETRY_DELAY_SEC)
                        continue # Continue to next loop iteration

                # Process the batch fetched from DB
                logger.info(f"Found {len(pending)} pending transactions in DB. Attempting upload.")
                for transaction_data in pending:
                    if self.stop_event.is_set(): break # Check stop event frequently
                    transaction_dict = dict(transaction_data) # Convert from sqlite3.Row
                    self._send_transaction(transaction_dict)
                    time.sleep(0.5) # Small delay between requests

            except Exception as e:
                logger.error(f"Error in network worker loop: {e}", exc_info=True)
                time.sleep(config.NETWORK_RETRY_DELAY_SEC) # Wait after error

        logger.info("Network worker thread stopped.")

    def _send_transaction(self, transaction_data):
        """Attempts to send a single transaction to the server."""
        transaction_id = transaction_data['id']
        payload = {
            'user_id': transaction_data['user_id'],
            'user_name': transaction_data['name'], # Send name for convenience
            'timestamp': transaction_data['timestamp'].isoformat(),
            'local_transaction_id': transaction_id # Send local ID for reference
        }
        try:
            logger.info(f"Attempting to send transaction {transaction_id} to {config.SERVER_URL}")
            response = requests.post(
                config.SERVER_URL,
                json=payload,
                timeout=config.NETWORK_TIMEOUT_SEC
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            logger.info(f"Transaction {transaction_id} sent successfully (Status: {response.status_code}).")
            self.db_manager.update_transaction_status(transaction_id, 'sent')
            return True

        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error sending transaction {transaction_id}. Server might be offline. Will retry later.")
            self.db_manager.update_transaction_status(transaction_id, 'pending') # Ensure it stays pending
            time.sleep(config.NETWORK_RETRY_DELAY_SEC) # Wait longer after connection error
            return False
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout sending transaction {transaction_id}. Will retry later.")
            self.db_manager.update_transaction_status(transaction_id, 'pending')
            time.sleep(config.NETWORK_RETRY_DELAY_SEC / 2) # Wait a bit before retrying
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending transaction {transaction_id}: {e}")
            # Consider marking as 'failed' after several attempts, but for now keep pending
            self.db_manager.update_transaction_status(transaction_id, 'pending') # Or 'failed'
            time.sleep(config.NETWORK_RETRY_DELAY_SEC / 2)
            return False

    def stop(self):
        """Signals the worker thread to stop."""
        logger.info("Stopping NetworkManager worker thread...")
        self.stop_event.set()
        # Add a small item to the queue to potentially wake up the worker if it's blocking on get()
        self.upload_queue.put(None)
        self.worker_thread.join(timeout=5) # Wait for the thread to finish
        logger.info("NetworkManager stopped.")