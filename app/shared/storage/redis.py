"""
Simple Redis client manager that creates and tracks clients.
"""

import asyncio
import atexit
import threading
from typing import Dict
from redis.asyncio import Redis
from loguru import logger

# Import centralized configuration
from ..config import config


try:
    from arq.connections import ArqRedis
    ARQ_AVAILABLE = True
except ImportError:
    ARQ_AVAILABLE = False
    logger.warning("arq not available, queue client functionality will be limited")


class RedisCacheSession:
    """
    Session for Redis cache client that provides context management.
    
    This class allows using a single cache client with with for automatic cleanup.
    """
    
    def __init__(self, manager: 'RedisManager', label: str):
        self.manager = manager
        self.label = label
        self.client = None
    
    def __enter__(self):
        """Sync context manager entry - get the cache client."""
        self.client = self.manager.get_cache_client(self.label)
        return self.client
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close the specific cache client."""
        if self.client:
            await self.manager.close_cache_client(self.label)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context manager exit - close the specific cache client."""
        # For sync context manager, we don't close the client immediately
        # The client will be managed by the RedisManager lifecycle
        pass


class RedisQueueSession:
    """
    Session for Redis queue client that provides context management.
    
    This class allows using a single queue client with with for automatic cleanup.
    """
    
    def __init__(self, manager: 'RedisManager', label: str):
        self.manager = manager
        self.label = label
        self.client = None
    
    def __enter__(self):
        """Sync context manager entry - get the queue client."""
        self.client = self.manager.get_queue_client(self.label)
        return self.client
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close the specific queue client."""
        if self.client:
            await self.manager.close_queue_client(self.label)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context manager exit - close the specific queue client."""
        # For sync context manager, we don't close the client immediately
        # The client will be managed by the RedisManager lifecycle
        pass


class RedisManager:
    """
    Simple Redis client manager.
    
    Features:
    - Creates and tracks Redis cache and queue clients
    - Loads connection strings from environment variables and demo env files
    - Supports both standalone and cluster modes
    - Ensures all clients are closed on process exit
    - Thread-safe singleton pattern
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
        """Initialize Redis manager."""
        if hasattr(self, '_initialized'):
            return
        
        self._cache_clients: Dict[str, Redis] = {}
        self._queue_clients: Dict[str, ArqRedis] = {}
        self._connection_strings: Dict[str, str] = {}
        self._connection_modes: Dict[str, str] = {}
        self._lock = threading.Lock()
        
        # Load connection strings from environment variables and demo env files
        self._load_connection_strings()
        
        # Register cleanup on process exit
        atexit.register(self._cleanup)
        
        self._initialized = True
    
    def _get_label_from_env_var(self, env_var: str) -> str:
        if env_var.startswith('REDIS_URL_'):
            return env_var[10:].lower()
        elif env_var != 'REDIS_URL' and env_var.startswith('REDIS_') and env_var.endswith('_URL'):
            return env_var.split('_')[1].lower()
        else:
            return None

    def _load_connection_strings(self):
        """Load Redis connection strings from centralized configuration."""
        # Look for REDIS_URL_XXX environment variables in config (excluding REDIS_URL_DEFAULT)
        for key, value in config.items():
            label = self._get_label_from_env_var(key)
            if label is None:
                continue
            if label in self._connection_strings:
                logger.warning(
                    "Redis connection string for label '{}' already exists, '{}' will override it", 
                    label, key
                )

            self._connection_strings[label] = value
            
            # Extract mode from query parameters
            mode = self._extract_mode_from_url(value)
            self._connection_modes[label] = mode
            
            # Hide password in logs for security
            safe_value = self._hide_password_in_connection_string(value)
            logger.info("Loaded Redis connection string for label '{}' (mode: {}): {}", label, mode, safe_value)
        
        # Handle default connection string with proper priority
        # Always use get_redis_url to ensure proper priority handling
        if 'default' not in self._connection_strings:
            default_url = config.get_redis_url('default')
            self._connection_strings['default'] = default_url
        
            # Extract mode from default URL
            mode = self._extract_mode_from_url(default_url)
            self._connection_modes['default'] = mode
        
            # Hide password in logs for security
            safe_default_url = self._hide_password_in_connection_string(default_url)
            logger.info("Using default Redis connection string (mode: {}): {}", mode, safe_default_url)
        
        # Log all loaded connection strings
        if self._connection_strings:
            safe_labels = list(self._connection_strings.keys())
            logger.info("Loaded {} Redis connection strings: {}", len(self._connection_strings), safe_labels)
        else:
            logger.warning("No Redis connection strings found")
    
    def _extract_mode_from_url(self, connection_string: str) -> str:
        """
        Extract mode (cluster|standalone) from connection string.
        
        Args:
            connection_string: Redis connection string
            
        Returns:
            Mode string: 'cluster' or 'standalone'
        """
        try:
            if 'mode=' in connection_string:
                # Extract mode from query parameters
                query_start = connection_string.find('?')
                if query_start != -1:
                    query_part = connection_string[query_start + 1:]
                    params = query_part.split('&')
                    for param in params:
                        if param.startswith('mode='):
                            mode = param.split('=')[1]
                            if mode in ['cluster', 'standalone']:
                                return mode

            if 'cluster' in connection_string:
                return 'cluster'

            return 'standalone'  # Default mode
        except Exception as e:
            logger.warning("Failed to extract mode from {}: {}", connection_string, e)
            return 'standalone'
    
    def _clean_connection_string(self, connection_string: str) -> str:
        """
        Remove mode parameter from connection string for actual connection.
        
        Args:
            connection_string: Original connection string
            
        Returns:
            Cleaned connection string without mode parameter
        """
        try:
            if 'mode=' in connection_string:
                # Remove mode parameter from query string
                query_start = connection_string.find('?')
                if query_start != -1:
                    base_url = connection_string[:query_start]
                    query_part = connection_string[query_start + 1:]
                    params = query_part.split('&')
                    
                    # Filter out mode parameter
                    clean_params = [param for param in params if not param.startswith('mode=')]
                    
                    if clean_params:
                        return f"{base_url}?{'&'.join(clean_params)}"
                    else:
                        return base_url
            return connection_string
        except Exception as e:
            logger.warning("Failed to clean connection string {}: {}", connection_string, e)
            return connection_string
    
    def _hide_password_in_connection_string(self, connection_string: str) -> str:
        """
        Hide password in Redis connection string for security logging.
        
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
    
    def get_cache_client(self, label: str = None) -> Redis:
        """
        Get Redis cache client by label.
        
        Args:
            label: Client label (defaults to 'default')
            
        Returns:
            Redis instance
            
        Raises:
            ValueError: If label not found
        """
        if label is None:
            label = 'default'
        
        with self._lock:
            if label not in self._cache_clients:
                if label not in self._connection_strings:
                    raise ValueError(f"No Redis connection string found for label '{label}'")
                
                # Create new cache client
                connection_string = self._connection_strings[label]
                mode = self._connection_modes.get(label, 'standalone')
                
                # Clean connection string (remove mode parameter)
                clean_url = self._clean_connection_string(connection_string)
                
                logger.info("Open Redis cache client for label '{}' (mode: {})", label, mode)
                
                if mode == 'cluster':
                    # For cluster mode, use cluster client
                    from redis.asyncio.cluster import RedisCluster
                    self._cache_clients[label] = RedisCluster.from_url(clean_url)
                else:
                    # For standalone mode, use regular client
                    self._cache_clients[label] = Redis.from_url(clean_url)
            
            return self._cache_clients[label]
    
    def get_queue_client(self, label: str = None) -> ArqRedis:
        """
        Get Redis queue client by label.
        
        Args:
            label: Client label (defaults to 'default')
            
        Returns:
            ArqRedis instance
            
        Raises:
            ValueError: If label not found or ArqRedis not available
        """
        if not ARQ_AVAILABLE:
            raise ImportError("ArqRedis is not available. Please install arq package.")
        
        if label is None:
            label = 'default'
        
        with self._lock:
            if label not in self._queue_clients:
                if label not in self._connection_strings:
                    raise ValueError(f"No Redis connection string found for label '{label}'")
                
                # Create new queue client
                connection_string = self._connection_strings[label]
                mode = self._connection_modes.get(label, 'standalone')
                
                # Clean connection string (remove mode parameter)
                clean_url = self._clean_connection_string(connection_string)
                
                logger.info("Open Redis queue client for label '{}' (mode: {})", label, mode)
                
                # Use ArqRedis.from_url for queue client
                self._queue_clients[label] = ArqRedis.from_url(clean_url)
            
            return self._queue_clients[label]
    
    async def close_cache_client(self, label: str):
        """Close specific cache client."""
        with self._lock:
            if label in self._cache_clients:
                try:
                    await self._cache_clients[label].aclose()
                    del self._cache_clients[label]
                    logger.info("Closed Redis cache client for label '{}'", label)
                except Exception as e:
                    logger.error("Error closing Redis cache client for label '{}': {}", label, e)
    
    async def close_queue_client(self, label: str):
        """Close specific queue client."""
        with self._lock:
            if label in self._queue_clients:
                try:
                    await self._queue_clients[label].aclose()
                    del self._queue_clients[label]
                    logger.info("Closed Redis queue client for label '{}'", label)
                except Exception as e:
                    logger.error("Error closing Redis queue client for label '{}': {}", label, e)
    
    async def close_all(self):
        """Close all clients."""
        with self._lock:
            # Get all client labels first
            cache_labels = list(self._cache_clients.keys())
            queue_labels = list(self._queue_clients.keys())
        
        # Close cache clients without holding the lock
        for label in cache_labels:
            await self.close_cache_client(label)
        
        # Close queue clients without holding the lock
        for label in queue_labels:
            await self.close_queue_client(label)
    
    def cache_session(self, label: str = None):
        """
        Get a cache client session for context management.
        
        Args:
            label: Client label (defaults to 'default')
            
        Returns:
            RedisCacheSession instance that manages the cache client lifecycle
        """
        return RedisCacheSession(self, label)
    
    def queue_session(self, label: str = None):
        """
        Get a queue client session for context management.
        
        Args:
            label: Client label (defaults to 'default')
            
        Returns:
            RedisQueueSession instance that manages the queue client lifecycle
        """
        return RedisQueueSession(self, label)
    
    def get_connection_string(self, label: str = None) -> str:
        """
        Retrieve the raw Redis connection string for a given label.

        Args:
            label: Connection label; pass None or 'default' for default connection.

        Returns:
            The stored connection string for the specified label.

        Raises:
            ValueError: If no connection string is registered for the label.
        """
        if label is None:
            label = 'default'

        connection_string = self._connection_strings.get(label)
        if connection_string is None:
            raise ValueError(f"No Redis connection string found for label '{label}'")

        return connection_string
    
    def get_connection_info(self) -> Dict[str, Dict[str, str]]:
        """
        Get connection information for debugging.
        
        Returns:
            Dictionary with connection strings and modes for each label
        """
        info = {}
        for label, connection_string in self._connection_strings.items():
            mode = self._connection_modes.get(label, 'standalone')
            clean_url = self._clean_connection_string(connection_string)
            info[label] = {
                'original_url': connection_string,
                'clean_url': clean_url,
                'mode': mode
            }
        return info
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close all clients."""
        await self.close_all()
    
    def __enter__(self):
        """Sync context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context manager exit - close all clients."""
        # Note: This is sync context manager, but close_all is async
        # In practice, you should use async context manager for RedisManager
        logger.warning("RedisManager sync context manager used. Consider using async context manager.")
    
    def _cleanup(self):
        """Cleanup method called on process exit."""
        # Use a more robust cleanup that doesn't require locks
        try:
            # Get all client labels without locking
            cache_labels = list(self._cache_clients.keys()) if hasattr(self, '_cache_clients') else []
            queue_labels = list(self._queue_clients.keys()) if hasattr(self, '_queue_clients') else []
            
            # Close cache clients
            for label in cache_labels:
                try:
                    if label in self._cache_clients:
                        client = self._cache_clients[label]
                        
                        # Redis clients have async aclose method
                        if hasattr(client, 'aclose') and callable(client.aclose):
                            import asyncio
                            
                            try:
                                # Try to get current event loop
                                current_event_loop = asyncio.get_running_loop()
                                # If we're in a running loop, schedule the coroutine
                                current_event_loop.create_task(client.aclose())
                                logger.info("Free redis cache client for '{}'", label)
                            except RuntimeError:
                                # No running loop or attached to a different loop, just ignore
                                pass
                        else:
                            logger.warning("Cache client for label '{}' has no aclose method", label)
                        
                        # Remove from clients dict
                        if label in self._cache_clients:
                            del self._cache_clients[label]
                except Exception as e:
                    logger.error("Error during cleanup of cache client '{}': {}", label, e)
            
            # Close queue clients
            for label in queue_labels:
                try:
                    if label in self._queue_clients:
                        client = self._queue_clients[label]
                        
                        # Redis clients have async aclose method
                        if hasattr(client, 'aclose') and callable(client.aclose):
                            import asyncio
                            
                            try:
                                # Try to get current event loop
                                current_event_loop = asyncio.get_running_loop()
                                # If we're in a running loop, schedule the coroutine
                                current_event_loop.create_task(client.aclose())
                                logger.info("Free redis queue client for '{}'", label)
                            except RuntimeError:
                                # No running loop or attached to a different loop, just ignore
                                pass
                        else:
                            logger.warning("Queue client for label '{}' has no aclose method", label)
                        
                        # Remove from clients dict
                        if label in self._queue_clients:
                            del self._queue_clients[label]
                except Exception as e:
                    logger.error("Error during cleanup of queue client '{}': {}", label, e)

        except Exception as e:
            logger.error("Error during cleanup: {}", e)
    
    async def _close_client(self, client, label: str, client_type: str):
        """Close a client asynchronously with proper error handling"""
        try:
            # Check if client is still valid and has aclose method
            if not hasattr(client, 'aclose') or not callable(client.aclose):
                logger.warning("{} client '{}' has no aclose method", client_type, label)
                return
                
            # Give the client a short timeout to close gracefully
            await asyncio.wait_for(client.aclose(), timeout=2.0)
            logger.info("Successfully closed {} client '{}'", client_type, label)
        except asyncio.TimeoutError:
            logger.warning("Timeout closing {} client '{}' - forcing close", client_type, label)
            # Force close by setting the connection pool to None
            if hasattr(client, 'connection_pool'):
                client.connection_pool = None
        except Exception as e:
            logger.error("Error closing {} client '{}': {}", client_type, label, e)
            # Force close by setting the connection pool to None
            if hasattr(client, 'connection_pool'):
                client.connection_pool = None
    
    def __del__(self):
        """Destructor to ensure cleanup."""
        try:
            self._cleanup()
        except Exception:
            # Ignore errors during destructor
            pass


# Global convenience functions
def get_redis_manager() -> RedisManager:
    """Get global RedisManager instance."""
    return RedisManager()


def get_redis_client(label: str = None) -> Redis:
    """Get Redis redis client (global function)."""
    if label is None:
        label = 'default'
        
    if label.endswith('queue'):
        return get_redis_manager().get_queue_client(label)
    else:
        return get_redis_manager().get_cache_client(label)


def get_cache_client(label: str = None) -> Redis:
    """Get Redis cache client (global function)."""
    return get_redis_manager().get_cache_client(label)


def get_queue_client(label: str = None) -> ArqRedis:
    """Get Redis queue client (global function)."""
    return get_redis_manager().get_queue_client(label)


def cache_session(label: str = None):
    """Get cache client session (global function)."""
    return get_redis_manager().cache_session(label)


def queue_session(label: str = None):
    """Get queue client session (global function)."""
    return get_redis_manager().queue_session(label)


def get_connection_string(label: str = None) -> str:
    """Get raw Redis connection string (global function)."""
    return get_redis_manager().get_connection_string(label)
