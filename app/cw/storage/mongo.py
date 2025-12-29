"""
Simple MongoDB client manager that creates and tracks clients.
"""

import atexit
import threading
from typing import Dict
from motor.motor_asyncio import AsyncIOMotorClient
from loguru import logger

# Import centralized configuration
from ..config import config


class ClientSession:
    """
    Session for MongoDB client that provides context management.
    
    This class allows using a single client with with for automatic cleanup.
    """
    
    def __init__(self, manager: 'MongoManager', label: str):
        self.manager = manager
        self.label = label
        self.client = None
    
    def __enter__(self) -> AsyncIOMotorClient:
        """Sync context manager entry - get the client."""
        self.client = self.manager.get_client(self.label)
        return self.client
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context manager exit - close the specific client."""
        if self.client:
            self.manager.close_client(self.label)


class MongoManager:
    """
    Simple MongoDB client manager.
    
    Features:
    - Creates and tracks MongoDB clients
    - Loads connection strings from environment variables and demo env files
    - Supports replica set connections with automatic detection
    - Configurable connection pool size
    - Ensures all clients are closed on process exit
    - Thread-safe singleton pattern
    
    Environment Variables Priority (highest to lowest):
    1. MONGO_URL_DEFAULT - Explicit default connection string
    2. MONGO_URL - System default connection string  
    3. Hardcoded fallback - mongodb://localhost:27017
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern: only one instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize MongoDB manager."""
        if hasattr(self, '_initialized'):
            return
        
        self._clients: Dict[str, AsyncIOMotorClient] = {}
        self._connection_strings: Dict[str, str] = {}
        self._max_pool_size: int = 5  # Default max pool size
        self._server_selection_timeout: int = 30000  # Default 30 seconds
        self._connect_timeout: int = 30000  # Default 30 seconds
        self._socket_timeout: int = 300000  # Default 5 minutes
        self._lock = threading.Lock()
        
        # Load connection strings from environment variables and demo env files
        self._load_connection_strings()
        
        # Load configuration
        self._load_max_pool_size()
        self._load_timeout_configs()
        
        # Register cleanup on process exit
        atexit.register(self._cleanup)
        
        self._initialized = True

    def _get_label_from_env_var(self, env_var: str) -> str:
        if env_var.startswith('MONGO_URL_'):
            return env_var[10:].lower()
        elif env_var != 'MONGO_URL' and env_var.startswith('MONGO_') and env_var.endswith('_URL'):
            return env_var.split('_')[1].lower()
        else:
            return None
    
    def _load_connection_strings(self):
        """Load MongoDB connection strings from centralized configuration."""
        # Look for MONGO_URL_XXX environment variables in config
        for key, value in config.items():
            label = self._get_label_from_env_var(key)
            if label is None:
                continue
            if label in self._connection_strings:
                logger.warning(
                    "MongoDB connection string for label '{}' already exists, '{}' will override it", 
                    label, key
                )

            self._connection_strings[label] = value
            # Hide password in logs for security
            safe_value = self._hide_password_in_connection_string(value)
            logger.info("Loaded MongoDB connection string for label '{}': {}", label, safe_value)

        # Handle default connection string with proper priority
        # Always use get_mongo_url to ensure proper priority handling
        if 'default' not in self._connection_strings:
            default_url = config.get_mongo_url('default')
            self._connection_strings['default'] = default_url
        else:
            default_url = self._connection_strings['default']

        # Hide password in logs for security
        safe_default_url = self._hide_password_in_connection_string(default_url)
        logger.info("Using default MongoDB connection string: {}", safe_default_url)

        # Log all loaded connection strings
        if self._connection_strings:
            safe_labels = list(self._connection_strings.keys())
            logger.info("Loaded {} MongoDB connection strings: {}", len(self._connection_strings), safe_labels)
        else:
            logger.warning("No MongoDB connection strings found")
    
    def _load_max_pool_size(self):
        """Load max pool size configuration from centralized configuration."""
        self._max_pool_size = config.get_mongo_max_pool_size()
        logger.info("Loaded MongoDB max pool size: {}", self._max_pool_size)
    
    def _load_timeout_configs(self):
        """Load timeout configurations from centralized configuration."""
        self._server_selection_timeout = config.get_mongo_server_selection_timeout()
        self._connect_timeout = config.get_mongo_connect_timeout()
        self._socket_timeout = config.get_mongo_socket_timeout()
        logger.info(
            "Loaded MongoDB parameters: server_selection={}ms connect={}ms socket={}ms", 
            self._server_selection_timeout, self._connect_timeout, self._socket_timeout
        )
    
    @property
    def max_pool_size(self) -> int:
        """Get the configured max pool size."""
        return self._max_pool_size
    
    @property
    def server_selection_timeout(self) -> int:
        """Get the configured server selection timeout in milliseconds."""
        return self._server_selection_timeout
    
    @property
    def connect_timeout(self) -> int:
        """Get the configured connection timeout in milliseconds."""
        return self._connect_timeout
    
    @property
    def socket_timeout(self) -> int:
        """Get the configured socket timeout in milliseconds."""
        return self._socket_timeout
    
    def _hide_password_in_connection_string(self, connection_string: str) -> str:
        """
        Hide password in MongoDB connection string for security logging.
        
        Args:
            connection_string: Original connection string
            
        Returns:
            Connection string with password hidden
        """
        try:
            # Check if connection string contains authentication
            if '@' in connection_string and '://' in connection_string:
                # Split the connection string
                protocol_part, rest = connection_string.split('://', 1)
                
                if '@' in rest:
                    # Find the last @ symbol (host part)
                    # This handles cases where password might contain @ symbols
                    last_at_index = rest.rfind('@')
                    if last_at_index != -1:
                        auth_part = rest[:last_at_index]
                        host_part = rest[last_at_index + 1:]
                        
                        # Check if auth part contains password (username:password)
                        if ':' in auth_part:
                            username, password = auth_part.split(':', 1)
                            
                            # Only hide password if both username and password are not empty
                            if username and password:
                                # Replace password with asterisks
                                safe_auth_part = f"{username}:***"
                                # Reconstruct connection string
                                safe_connection_string = f"{protocol_part}://{safe_auth_part}@{host_part}"
                                return safe_connection_string
                            # If username or password is empty, return original
                            return connection_string
            
            # If no password found, return original
            return connection_string
            
        except Exception:
            # If parsing fails, return original string
            return connection_string
    
    def _extract_replica_set_name(self, connection_string: str) -> str:
        """
        Extract replica set name from connection string.
        
        Args:
            connection_string: MongoDB connection string
            
        Returns:
            Replica set name if found, None otherwise
        """
        try:
            # Parse connection string to extract replica set name
            if 'replicaSet=' in connection_string:
                # Extract replica set name from query parameters
                query_start = connection_string.find('?')
                if query_start != -1:
                    query_part = connection_string[query_start + 1:]
                    params = query_part.split('&')
                    for param in params:
                        if param.startswith('replicaSet='):
                            return param.split('=')[1]
            return None
        except Exception as e:
            logger.warning("Failed to extract replica set name from {}: {}", connection_string, e)
            return None

    def _create_client_with_options(self, connection_string: str, label: str) -> AsyncIOMotorClient:
        """
        Create MongoDB client with proper options including replica set configuration.
        
        Args:
            connection_string: MongoDB connection string
            label: Client label for logging
            
        Returns:
            AsyncIOMotorClient instance
        """
        try:
            # Extract replica set name if present
            replica_set_name = self._extract_replica_set_name(connection_string)
            
            if replica_set_name:
                logger.info("Open MongoDB client for label '{}' with replica set '{}'", label, replica_set_name)
                # Create client with replica set options
                client = AsyncIOMotorClient(
                    connection_string,
                    replicaSet=replica_set_name,
                    serverSelectionTimeoutMS=self._server_selection_timeout,
                    connectTimeoutMS=self._connect_timeout,
                    socketTimeoutMS=self._socket_timeout,
                    maxPoolSize=self._max_pool_size
                )
            else:
                logger.info("Open MongoDB client for label '{}'", label)
                # Create client without replica set options
                client = AsyncIOMotorClient(
                    connection_string,
                    serverSelectionTimeoutMS=self._server_selection_timeout,
                    connectTimeoutMS=self._connect_timeout,
                    socketTimeoutMS=self._socket_timeout,
                    maxPoolSize=self._max_pool_size
                )
            
            return client
            
        except Exception as e:
            logger.error("Failed to create MongoDB client for label '{}': {}", label, e)
            raise
    
    def get_client(self, label: str = None) -> AsyncIOMotorClient:
        """
        Get MongoDB client by label.
        
        Args:
            label: Client label (defaults to 'default')
            
        Returns:
            AsyncIOMotorClient instance
            
        Raises:
            ValueError: If label not found
        """
        if label is None:
            label = 'default'
        
        with self._lock:
            if label not in self._clients:
                if label not in self._connection_strings:
                    raise ValueError(f"No MongoDB connection string found for label '{label}'")
                
                # Create new client
                connection_string = self._connection_strings[label]
                self._clients[label] = self._create_client_with_options(connection_string, label)
            
            return self._clients[label]
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close all clients."""
        self.close_all()  # close_all is now sync
    
    def __enter__(self):
        """Sync context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context manager exit - close all clients."""
        self.close_all()
    
    def client_session(self, label: str = None):
        """
        Get a client session for context management.
        
        Args:
            label: Client label (defaults to 'default')
            
        Returns:
            ClientSession instance that manages the client lifecycle
        """
        return ClientSession(self, label)
    
    def get_connection_info(self) -> Dict[str, str]:
        """
        Get connection information for debugging.
        
        Returns:
            Dictionary with connection strings for each label
        """
        info = {}
        for label, connection_string in self._connection_strings.items():
            info[label] = {
                'connection_string': connection_string,
                'safe_connection_string': self._hide_password_in_connection_string(connection_string)
            }
        return info
    
    def close_client(self, label: str):
        """Close specific client."""
        with self._lock:
            if label in self._clients:
                try:
                    self._clients[label].close()  # AsyncIOMotorClient.close() is sync
                    del self._clients[label]
                    logger.info("Closed MongoDB client for label '{}'", label)
                except Exception as e:
                    logger.error("Error closing MongoDB client for label '{}': {}", label, e)
    
    def close_all(self):
        """Close all clients."""
        with self._lock:
            # Get all client labels first
            client_labels = list(self._clients.keys())
        
        # Close clients without holding the lock
        for label in client_labels:
            self.close_client(label)
        
    def _cleanup(self):
        """Cleanup method called on process exit."""
        # Use a more robust cleanup that doesn't require locks
        try:
            # Get all client labels without locking
            client_labels = list(self._clients.keys()) if hasattr(self, '_clients') else []
            
            # Close each client directly without using the manager methods
            for label in client_labels:
                try:
                    if label in self._clients:
                        client = self._clients[label]
                        
                        # Check if client has a close method
                        if hasattr(client, 'close') and callable(client.close):
                            # Check if close method is async (returns coroutine)
                            import asyncio
                            import inspect
                            
                            if inspect.iscoroutinefunction(client.close):
                                # Async close method
                                try:
                                    try:
                                        current_event_loop = asyncio.get_running_loop()
                                        # If we're in a running loop, we can't use run_until_complete
                                        # Schedule the coroutine instead
                                        current_event_loop.create_task(client.close())
                                        logger.info("Free mongo client for '{}'", label)
                                    except RuntimeError:
                                        # No running loop, create a new one
                                        current_event_loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(current_event_loop)
                                        try:
                                            current_event_loop.run_until_complete(client.close())
                                            logger.info("Free mongo client for '{}'", label)
                                        finally:
                                            current_event_loop.close()
                                except Exception as e:
                                    logger.error("Error closing client '{}' during cleanup: {}", label, e)
                            else:
                                # Sync close method
                                try:
                                    client.close()
                                    logger.info("Free mongo client for '{}'", label)
                                except Exception as e:
                                    logger.error("Error closing client '{}' during cleanup: {}", label, e)
                        else:
                            logger.warning("Client for label '{}' has no close method", label)
                        
                        # Remove from clients dict
                        if label in self._clients:
                            del self._clients[label]
                except Exception as e:
                    logger.error("Error during cleanup of client '{}': {}", label, e)
        except Exception as e:
            logger.error("Error during cleanup: {}", e)
    
    def __del__(self):
        """Destructor to ensure cleanup."""
        try:
            self._cleanup()
        except Exception:
            # Ignore errors during destructor
            pass


# Global instance
_mongo_manager = None


def get_mongo_manager() -> MongoManager:
    """Get the global MongoDB manager instance."""
    global _mongo_manager
    if _mongo_manager is None:
        _mongo_manager = MongoManager()
    return _mongo_manager


def get_mongo_client(label: str = None) -> AsyncIOMotorClient:
    """Get MongoDB client by label."""
    return get_mongo_manager().get_client(label)


def get_mongo_session(label: str = None):
    """Get MongoDB client session with context management."""
    return get_mongo_manager().client_session(label)
