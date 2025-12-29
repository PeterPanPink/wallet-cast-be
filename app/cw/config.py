"""
Centralized configuration management (sanitized demo).

This repository is a public portfolio showcase. To reduce the risk of leaking
private configuration patterns, we intentionally avoid auto-loading hidden
dotfiles commonly used for local secrets.

Instead, this demo supports:
1) `env.example` (committed, safe placeholders)
2) `env.local` (optional, MUST NOT be committed)
3) System environment variables (highest priority)
"""

import os
import time
import threading
import orjson
from pathlib import Path
from dotenv import dotenv_values
from loguru import logger


class EnvironConfig:
    """
    Singleton configuration class that loads environment variables from demo env files
    and system environment, providing dictionary-like access with default values.
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EnvironConfig, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._config = {}
            self._load_config()
            EnvironConfig._initialized = True
    
    def _load_config(self):
        """
        Load configuration from demo env files and system environment.
        
        Priority order (later overrides earlier):
        1. env.example (committed placeholders)
        2. env.local (developer-local, not committed)
        3. System environment variables (highest priority)
        """
        root = Path(__file__).parent.parent.parent

        example_path = root / "env.example"
        if example_path.exists():
            env_values = dotenv_values(example_path)
            self._config.update(env_values)
            logger.info("Loaded environment variables from {}", example_path)

        local_path = root / "env.local"
        if local_path.exists():
            local_values = dotenv_values(local_path)
            self._config.update(local_values)
            logger.info("Loaded and overrode environment variables from {}", local_path)
        
        # Add system environment variables (highest priority)
        self._config.update(os.environ)
    
    def __getitem__(self, key):
        """
        Get configuration value by key.
        
        Args:
            key: Configuration key
            
        Returns:
            str: Configuration value
            
        Raises:
            KeyError: If key not found and no default provided
            ValueError: If key value is None
        """
        if key not in self._config:
            raise KeyError(f"Configuration key '{key}' not found")
        
        return self._config[key]
    
    def get(self, key, default=None):
        """
        Get configuration value by key with optional default.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            str: Configuration value or default
            
        Raises:
            ValueError: If key value is None
        """
        return self._config.get(key, default)
    
    def clear(self):
        """
        Clear configuration.
        Useful for testing or when configuration files change.
        """
        self._config.clear()
        logger.info("Configuration cleared")

    def reload(self):
        """
        Reload configuration from files and environment.
        Useful for testing or when configuration files change.
        """
        self._config.clear()
        self._load_config()
        logger.info("Configuration reloaded")
    
    def __contains__(self, key):
        """Check if configuration key exists."""
        return key in self._config
    
    def __iter__(self):
        """Iterate over configuration keys."""
        return iter(self._config)
    
    def keys(self):
        """Get all configuration keys."""
        return self._config.keys()
    
    def values(self):
        """Get all configuration values."""
        return self._config.values()
    
    def items(self):
        """Get all configuration key-value pairs."""
        return self._config.items()
    
    def get_redis_url(self, label: str = "default") -> str:
        """
        Get Redis connection URL for a specific label.
        
        Args:
            label: Redis connection label (default: "default")
            
        Returns:
            str: Redis connection URL
        """
        if label == "default":
            # Try REDIS_URL_DEFAULT first, then REDIS_URL, then fallback
            try:
                url = self.get('REDIS_URL_DEFAULT')
                if url:
                    return url
            except (KeyError, ValueError):
                pass
            
            try:
                url = self.get('REDIS_URL')
                if url:
                    return url
            except (KeyError, ValueError):
                pass
            
            return 'redis://localhost:6379'
        else:
            # Try REDIS_URL_<LABEL>
            try:
                return self.get(f'REDIS_URL_{label.upper()}')
            except (KeyError, ValueError):
                return ''
    
    def get_postgres_url(self, label: str = "default") -> str:
        """
        Get Postgres connection URL for a specific label.
        
        Args:
            label: Postgres connection label (default: "default")
            
        Returns:
            str: Postgres connection URL
        """
        if label == "default":
            # Try POSTGRES_URL_DEFAULT first, then POSTGRES_URL, then fallback
            try:
                url = self.get('POSTGRES_URL_DEFAULT')
                if url:
                    return url
            except (KeyError, ValueError):
                pass
            
            try:
                url = self.get('POSTGRES_URL')
                if url:
                    return url
            except (KeyError, ValueError):
                pass
            
            return 'postgresql://localhost:5432/postgres'
        else:
            # Try REDIS_URL_<LABEL>
            try:
                return self.get(f'POSTGRES_URL_{label.upper()}')
            except (KeyError, ValueError):
                return ''
    
    def get_mongo_url(self, label: str = "default") -> str:
        """
        Get MongoDB connection URL for a specific label.
        
        Args:
            label: MongoDB connection label (default: "default")
            
        Returns:
            str: MongoDB connection URL
        """
        if label == "default":
            # Try MONGO_URL_DEFAULT first, then MONGO_URL, then fallback
            try:
                url = self.get('MONGO_URL_DEFAULT')
                if url:
                    return url
            except (KeyError, ValueError):
                pass
            
            try:
                url = self.get('MONGO_URL')
                if url:
                    return url
            except (KeyError, ValueError):
                pass
            
            return 'mongodb://localhost:27017'
        else:
            # Try MONGO_URL_<LABEL>
            try:
                return self.get(f'MONGO_URL_{label.upper()}')
            except (KeyError, ValueError):
                return ''
    
    def get_mongo_max_pool_size(self) -> int:
        """
        Get MongoDB maximum pool size from configuration.
        
        Returns:
            int: Maximum pool size (1-100, default: 5)
        """
        try:
            size = int(self.get('MONGO_MAX_POOL_SIZE', '5'))
            if 1 <= size <= 100:
                return size
            else:
                logger.warning("MONGO_MAX_POOL_SIZE value {} is out of range (1-100), defaulting to 5", size)
                return 5
        except (ValueError, TypeError):
            logger.warning("Invalid MONGO_MAX_POOL_SIZE value '{}', defaulting to 5", self.get('MONGO_MAX_POOL_SIZE'))
            return 5
    
    def get_mongo_server_selection_timeout(self) -> int:
        """
        Get MongoDB server selection timeout from configuration.
        
        Returns:
            int: Server selection timeout in milliseconds (default: 30000)
        """
        try:
            timeout = int(self.get('MONGO_SERVER_SELECTION_TIMEOUT', '30000'))
            if timeout > 0:
                return timeout
            else:
                logger.warning("MONGO_SERVER_SELECTION_TIMEOUT value {} must be positive, defaulting to 30000", timeout)
                return 30000
        except (ValueError, TypeError):
            logger.warning("Invalid MONGO_SERVER_SELECTION_TIMEOUT value '{}', defaulting to 30000", self.get('MONGO_SERVER_SELECTION_TIMEOUT'))
            return 30000
    
    def get_mongo_connect_timeout(self) -> int:
        """
        Get MongoDB connection timeout from configuration.
        
        Returns:
            int: Connection timeout in milliseconds (default: 30000)
        """
        try:
            timeout = int(self.get('MONGO_CONNECT_TIMEOUT', '30000'))
            if timeout > 0:
                return timeout
            else:
                logger.warning("MONGO_CONNECT_TIMEOUT value {} must be positive, defaulting to 30000", timeout)
                return 30000
        except (ValueError, TypeError):
            logger.warning("Invalid MONGO_CONNECT_TIMEOUT value '{}', defaulting to 30000", self.get('MONGO_CONNECT_TIMEOUT'))
            return 30000
    
    def get_mongo_socket_timeout(self) -> int:
        """
        Get MongoDB socket timeout from configuration.
        
        Returns:
            int: Socket timeout in milliseconds (default: 300000)
        """
        try:
            timeout = int(self.get('MONGO_SOCKET_TIMEOUT', '300000'))
            if timeout > 0:
                return timeout
            else:
                logger.warning("MONGO_SOCKET_TIMEOUT value {} must be positive, defaulting to 300000", timeout)
                return 300000
        except (ValueError, TypeError):
            logger.warning("Invalid MONGO_SOCKET_TIMEOUT value '{}', defaulting to 300000", self.get('MONGO_SOCKET_TIMEOUT'))
            return 300000


class CustomConfig:
    """
    Custom YAML-backed configuration.

    - Searches parent directories for cw-lib.yml starting from project root
    - Loads into an internal dictionary when possible (requires PyYAML if present)
    - Provides dict-like access and convenience getters used by the library
    """

    _instance = None
    _initialized = False
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(CustomConfig, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._data = {}
            self._path = self._find_yaml()
            if self._path:
                self._data = self._load_yaml(self._path) or {}
            CustomConfig._initialized = True

    def _find_yaml(self):
        try:
            start = Path(__file__).parent  # parent of the library installed path
            for base in [start] + list(start.parents):
                candidate = base / 'cw-lib.yml'
                if candidate.exists() and candidate.is_file():
                    logger.info("Loaded custom config from {}", candidate)
                    return candidate
        except Exception as e:
            logger.warning("Failed searching cw-lib.yml: {}", e)
        return None

    def _load_yaml(self, path: Path):
        try:
            import yaml  # type: ignore
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except ModuleNotFoundError:
            logger.warning("PyYAML not installed; skipping cw-lib.yml load")
            return {}
        except Exception as e:
            logger.error("Failed to load {}: {}", path, e)
            return {}

    def __getitem__(self, key):
        if key not in self._data:
            raise KeyError(f"Configuration key '{key}' not found")
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)  

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get_service_code(self) -> str:
        return self.get_dynamic_config_root_key().split(':')[0]

    def get_dynamic_config_root_key(self) -> str:
        return self._data.get('dynamic_config_root_key', 'cw-lib:config')

    def get_dynamic_config_refresh_interval(self) -> int:
        return self._data.get('dynamic_config_refresh_interval', 10)

    def get_redis_queue_label(self) -> str:
        return self._data.get('redis_queue_label', 'default')

    def get_redis_major_label(self) -> str:
        return self._data.get('redis_major_label', 'default')

    def get_mongo_label(self) -> str:
        return self._data.get('mongo_label', 'default')

    def get_pgdbs_label(self) -> str:
        return self._data.get('pgdbs_label', 'default')


# Global instance for custom YAML config
custom_config = CustomConfig()


class DynamicConfig:
    """
    Dynamic configuration class that loads configuration from Redis with caching.
    This class is a singleton per redis_label.
    """
    
    _instances = {}
    _lock = {}  # Per-instance locks for thread safety
    
    def __new__(cls, redis_label: str = None):
        if redis_label is None:
            redis_label = 'default'

        if redis_label not in cls._instances:
            cls._instances[redis_label] = super(DynamicConfig, cls).__new__(cls)
            cls._lock[redis_label] = threading.Lock()
        return cls._instances[redis_label]
    
    def __init__(self, redis_label: str):
        if hasattr(self, '_initialized'):
            return
        
        self.redis_label = redis_label
        self._config = {}
        self._last_refresh_time = 0
        self._initialized = True
        
        # Get Redis client
        from .storage.redis import get_cache_client
        self._redis_client = get_cache_client(redis_label)
        
        # Get configuration keys
        self._config_root_key = custom_config.get_dynamic_config_root_key()
        self._refresh_interval = int(custom_config.get_dynamic_config_refresh_interval())
    
    async def reload(self, code: str = None):
        """
        Reload configuration from Redis for the given code.
        
        Args:
            code: Configuration code to load
        """
        if not code:
            code = 'default'
        
        current_time = time.time()
        root = f'{self._config_root_key}:{{{code}}}'
        
        # Check if we need to refresh based on time interval
        if current_time - self._last_refresh_time < self._refresh_interval:
            logger.debug("Skipping reload due to refresh interval for: {}", root)
            return
        
        # Check if configuration has been updated
        updated_key = f'{root}_updated'
        
        try:
            # Get the last update time from Redis
            updated_time_str = await self._redis_client.get(updated_key)
            if updated_time_str:
                updated_time = int(updated_time_str)
                # If the configuration hasn't been updated since our last refresh, skip reload
                if updated_time <= self._last_refresh_time:
                    logger.debug("Configuration not updated since last refresh for: {}", root)
                    return
        except Exception as e:
            logger.warning("Failed to check update time for: {} - {}", root, e)
        
        # Load configuration from Redis
        try:
            data = await self._redis_client.get(root)
            if not data:
                logger.warning("Configuration not found: {}", root)
                return
            
            # Parse JSON data
            root_data = orjson.loads(data)
            if 'keys' not in root_data:
                logger.warning("Invalid configuration format: {} - missing 'keys' field", root)
                return
            
            # Load all configuration data based on keys
            config_data = {}

            def decode_value(v):
                try:
                    v_str = v.decode('utf-8')
                    if v_str.lower() in ['true', 'false']:
                        return v_str.lower() == 'true'
                    else:
                        return orjson.loads(v_str)
                except Exception:
                    return v_str

            for k, v in root_data['keys'].items():
                cache_key = f'{root}:{k}'
                if v == 'set':
                    d = await self._redis_client.smembers(cache_key)
                    logger.debug('Getting set: {} = {}', cache_key, d)
                    config_data[k] = {decode_value(v1) for v1 in d}
                elif v == 'list':
                    d = await self._redis_client.lrange(cache_key, 0, -1)
                    logger.debug('Getting list: {} = {}', cache_key, d)
                    config_data[k] = [decode_value(v1) for v1 in d]
                elif v == 'map':
                    d = await self._redis_client.hgetall(cache_key)
                    logger.debug('Getting map: {} = {}', cache_key, d)
                    config_data[k] = {
                        k1.decode('utf-8'): decode_value(v1) 
                        for k1, v1 in d.items()
                    }
                else:
                    d = await self._redis_client.get(cache_key)
                    if not d:
                        logger.warning('Configuration not found for key: {}', cache_key)
                        continue
                    logger.debug('Getting str: {}={}', cache_key, d)
                    config_data[k] = decode_value(d)
            
            # Update internal cache
            with self._lock[self.redis_label]:
                self._config = config_data
                self._last_refresh_time = current_time
            
            logger.info("Reloaded configuration {} with {} keys", root, len(config_data))
            
        except Exception as e:
            logger.error("Failed to reload configuration: {} - {}", root, e)
    
    def get(self, key: str, default=None):
        """
        Get configuration value by key.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        return self._config.get(key, default)
    
    def __getitem__(self, key):
        """
        Get configuration value by key.
        
        Args:
            key: Configuration key
            
        Returns:
            Configuration value
            
        Raises:
            KeyError: If key not found
        """
        if key not in self._config:
            raise KeyError(f"Configuration key '{key}' not found")
        return self._config[key]
    
    def __contains__(self, key):
        """Check if configuration key exists."""
        return key in self._config
    
    def __iter__(self):
        """Iterate over configuration keys."""
        return iter(self._config)
    
    def keys(self):
        """Get all configuration keys."""
        return self._config.keys()
    
    def values(self):
        """Get all configuration values."""
        return self._config.values()
    
    def items(self):
        """Get all configuration key-value pairs."""
        return self._config.items()


# Global configuration instance
config = EnvironConfig()



def get_dynamic_config():
    return DynamicConfig(custom_config.get_redis_major_label())
