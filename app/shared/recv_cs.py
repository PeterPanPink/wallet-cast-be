import time
import asyncio
import uuid
import orjson
import socket
import hashlib
from bson import ObjectId
from pymongo.errors import OperationFailure
from loguru import logger

from .worker import healthcheck
from .config import custom_config
from .domain.entity_change import get_bucket
from .api.utils import format_error


redis_major_label = custom_config.get_redis_major_label()
redis_queue_label = custom_config.get_redis_queue_label()


def get_worker_id():
    """Generate a unique worker ID."""
    hostname = socket.gethostname()
    process_id = str(uuid.uuid4())[:8]  # Use first 8 chars of UUID
    return f"{hostname}-{process_id}"


def get_recv_key(ctx, key: str):
    return f'{ctx["svc_key_recv"]}:{key}'


async def save_resume_token(ctx, resume_token):
    """Save resume token to Redis (only master can update)."""
    try:
        if await is_master_worker(ctx):
            await ctx[redis_major_label].set(
                get_recv_key(ctx, 'token'),
                orjson.dumps(resume_token),
                ex=7 * 24 * 3600  # 7 days TTL
            )
            logger.debug('Resume token saved by master')
    except Exception as e:
        logger.warning('Failed to save resume token: {}', e)


async def load_resume_token(ctx):
    """Load resume token from Redis."""
    try:
        token_data = await ctx[redis_major_label].get(get_recv_key(ctx, 'token'))
        if token_data:
            return orjson.loads(token_data)
    except Exception as e:
        logger.warning('Failed to load resume token: {}', e)
    return None


def calculate_change_id_from_resume_token(resume_token):
    """Calculate change_id from resume token using SHA256 first 32 chars."""
    try:
        # Convert resume token to string and calculate SHA256
        token_str = orjson.dumps(resume_token).decode('utf-8')
        sha256_hash = hashlib.sha256(token_str.encode('utf-8')).hexdigest()
        # Return first 32 characters
        return sha256_hash[:32]
    except Exception as e:
        logger.warning('Failed to calculate change_id from resume token: {}', e)
        # Fallback to a default value
        return hashlib.sha256(str(uuid.uuid4()).encode('utf-8')).hexdigest()[:32]


async def enable_preimages_if_needed(mongo_db, collections):
    """
    Enable pre-images for collections if not already enabled
    This is required for fullDocumentBeforeChange to work properly
    """
    for coll_name in collections:
        try:
            # Check if pre-images are already enabled
            coll_info = await mongo_db.command('listCollections', filter={'name': coll_name})
            
            if coll_info['cursor']['firstBatch']:
                coll_options = coll_info['cursor']['firstBatch'][0].get('options', {})
                change_stream_options = coll_options.get('changeStreamPreAndPostImages', {})
                
                if not change_stream_options.get('enabled', False):
                    logger.info('Enabling pre-images for collection: {}', coll_name)
                    await mongo_db.command('collMod', coll_name, changeStreamPreAndPostImages={'enabled': True})
                else:
                    logger.debug('Pre-images already enabled for collection: {}', coll_name)
        except Exception as e:
            logger.warning('Could not enable pre-images for collection {}: {}', coll_name, e)


# Global state for master/standby status
_worker_status = {'is_master': False, 'worker_id': None}


def get_bucket_count(ctx):
    try:
        bucket_count = int(ctx.get('bucket_count', 1))
    except Exception:
        bucket_count = 1
        logger.warning('Using default bucket count: {}', bucket_count)
    return bucket_count


async def run(ctx):
    """
    Change stream listener with master/standby functionality.
    """
    collection_names = ctx['source_colls']
    logger.info('Start change stream listener for collections: {}', collection_names)

    source_db = ctx[ctx['source_label']].get_database()
    await enable_preimages_if_needed(source_db, collection_names)
    
    # Load resume token for resuming from last position
    resume_token = await load_resume_token(ctx)
    
    # Start change stream with pipeline to filter collections
    pipeline = [
        {
            '$match': {
                'ns.coll': {'$in': collection_names}
            }
        }
    ]
    
    # Change stream options for non-blocking operation
    options = {
        'full_document': 'updateLookup',
        'full_document_before_change': 'whenAvailable',  # Include full document when available (for deletes)
        'batch_size': 100,
        'max_await_time_ms': 1000,  # Wait up to 1 second for new changes
    }
    
    # Add resume token if available
    if resume_token:
        options['resume_after'] = resume_token
        logger.info('Resuming change stream from token: {}', resume_token)
    else:
        logger.info('Starting change stream from current time')
    
    for attemps in range(5):
        try:
            async with source_db.watch(pipeline, **options) as stream:
                logger.info('Change stream started successfully')
                
                # Create tasks for concurrent execution
                tasks = [
                    asyncio.create_task(process_event(ctx, stream)),
                    asyncio.create_task(acquire_lease(ctx)),
                    asyncio.create_task(enqueue_notify_if_backlog(ctx)),
                ]
                
                pending = tasks  # Initialize pending tasks
                try:
                    # Wait for any task to complete (or fail)
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    
                    # Check if any task failed
                    for task in done:
                        if task.exception():
                            logger.error('Task failed: {}', task.exception())
                            raise task.exception()
                            
                except asyncio.CancelledError:
                    logger.info('Change stream worker was cancelled')
                    raise
                finally:
                    # Cancel remaining tasks gracefully
                    for task in pending:
                        if not task.done():
                            task.cancel()
                            try:
                                await task
                            except asyncio.CancelledError:
                                logger.info('Task cancelled gracefully')
                            except Exception as e:
                                logger.warning('Error cancelling task: {}', e)
                        
        except Exception as e:
            logger.error('Change stream error: {}', e.code)
            if e.code == 280:
                logger.info('Change stream cursor was interrupted (likely during shutdown), remove resume token')
                await ctx[redis_major_label].delete(get_recv_key(ctx, 'token'))

            logger.info('Retrying in {} seconds... (attempt {}/{})', 2 ** attemps, attemps + 1, 5)
            await asyncio.sleep(2 ** (5 - attemps))

    raise Exception('Change stream error')


async def enqueue_notify(ctx, coll_name: str, bucket: int):
    notify_queue = ctx['notify_queue']
    notify_entry = ctx['notify_entry']
    major_cache = ctx[redis_major_label]
    queue_cache = ctx[redis_queue_label]

    queue_size = await queue_cache.zcard(notify_queue)

    if queue_size > 10_000:
        logger.warning('Notify queue size is too large: queue={} size={}', notify_queue, queue_size)
        return

    recv_key = get_recv_key(ctx, f'{coll_name}:{bucket}')
    oldest = await major_cache.zrange(recv_key, 0, 0, withscores=True)
    oldest_score = int(oldest[0][1]) if oldest else None
    if oldest_score is None:
        logger.warning('No oldest score: coll_name={} bucket={} recv_key={} queue={}', 
            coll_name, bucket, recv_key, notify_queue
        )
        return

    job_id = f"{'-'.join(recv_key.split(':')[2:])}-{oldest_score}"

    job = await queue_cache.enqueue_job(
        notify_entry, coll_name=coll_name, recv_key=recv_key, bucket=bucket,
        _job_id=job_id, _queue_name=notify_queue
    )

    if job is not None:
        logger.debug('Job enqueued: coll_name={} recv_key={} bucket={} queue={} job_id={}', 
            coll_name, recv_key, bucket, notify_queue, job_id
        )
    else:
        logger.debug('Job already exists: coll_name={} recv_key={} bucket={} queue={} job_id={}', 
            coll_name, recv_key, bucket, notify_queue, job_id,
        )


async def enqueue_notify_if_backlog(ctx):
    bucket_count = get_bucket_count(ctx)

    while True:
        for collection_name in ctx['source_colls']:
            for bucket in range(bucket_count):
                await enqueue_notify(ctx, collection_name, bucket)

        await asyncio.sleep(1)


async def process_event(ctx, stream):
    """Process change stream events with master/standby logic."""
    # Get initial master status
    is_master = await is_master_worker(ctx)
    logger.info('Worker started as: {}', 'MASTER' if is_master else 'STANDBY')
    
    change_count = 0
    last_status_check = 0
    
    try:
        async for change in stream:
            change_count += 1

            # Check master status every 10 changes or every 30 seconds
            current_time = asyncio.get_event_loop().time()
            if change_count % 10 == 0 or (current_time - last_status_check) > 30:
                is_master = await is_master_worker(ctx)
                last_status_check = current_time
                logger.info('Status check: {} (change #{})', 'MASTER' if is_master else 'STANDBY', change_count)
            else:
                # Use global state for faster access
                is_master = _worker_status.get('is_master', False)
            
            namespace = change.get('ns', {})
            collection_name = namespace.get('coll', 'unknown')
            operation_type = change.get('operationType', 'unknown')
            
            if is_master:
                # Master worker: process and output data
                logger.info('Master processing change: {} {}', collection_name, operation_type)
                await process_change_data(ctx, change)
            else:
                # Standby worker: only log, don't process
                logger.info('Standby worker received change: {} {} (not processing)', collection_name, operation_type)
            
    except OperationFailure as e:
        # Handle cursor interruption (normal during shutdown)
        if e.code == 237:  # CursorKilled
            logger.info('Change stream cursor was interrupted (likely during shutdown)')
        else:
            logger.error('Change stream operation failed: {}', e)
            raise
    except asyncio.CancelledError:
        logger.info('Change stream processing was cancelled')
        raise
    except Exception as e:
        logger.error('Unexpected error in change stream: {}', e)
        raise


async def acquire_lease(ctx):
    """Acquire and maintain master lease."""
    worker_id = get_worker_id()
    lease_key = get_recv_key(ctx, 'lease')
    lease_ttl = 15  # 15 seconds TTL
    
    # Initialize global state
    _worker_status['worker_id'] = worker_id
    
    while True:
        try:
            await healthcheck(ctx, int(time.time() * 1000))
                        
            # Try to acquire or renew lease
            acquired = await ctx[redis_major_label].set(lease_key, worker_id, nx=True, ex=lease_ttl)
            
            if acquired:
                if not _worker_status['is_master']:
                    logger.info('Acquired master lease: {}', worker_id)
                    _worker_status['is_master'] = True
            else:
                # Try to renew lease if we already own it
                current_owner = await ctx[redis_major_label].get(lease_key)
                if current_owner and current_owner.decode('utf-8') == worker_id:
                    # Renew our lease
                    await ctx[redis_major_label].expire(lease_key, lease_ttl)
                    if not _worker_status['is_master']:
                        logger.info('Renewed master lease: {}', worker_id)
                        _worker_status['is_master'] = True
                    else:
                        logger.debug('Renewed master lease: {}', worker_id)
                else:
                    if _worker_status['is_master']:
                        logger.info('Lost master lease, current master: {}', 
                                  current_owner.decode('utf-8') if current_owner else 'None')
                        _worker_status['is_master'] = False
                    else:
                        logger.debug('Standby worker, current master: {}', 
                                   current_owner.decode('utf-8') if current_owner else 'None')
            
            # Wait 10 seconds before next lease check (renew every 10s, TTL is 15s)
            await asyncio.sleep(10)
            
        except asyncio.CancelledError:
            logger.info('Lease acquisition cancelled')
            break
        except Exception as e:
            logger.error('Error in lease acquisition: {}', e)
            await asyncio.sleep(5)  # Wait before retry on error


async def is_master_worker(ctx):
    """Check if this worker is the current master."""
    try:
        # Use global state first (faster)
        if _worker_status['worker_id'] and _worker_status['is_master']:
            return True
        
        # Fallback to Redis check if global state is not set
        worker_id = get_worker_id()
        lease_key = get_recv_key(ctx, 'lease')
        
        current_owner = await ctx[redis_major_label].get(lease_key)
        if current_owner:
            is_master = current_owner.decode('utf-8') == worker_id
            # Update global state
            _worker_status['is_master'] = is_master
            _worker_status['worker_id'] = worker_id
            return is_master
        return False
    except Exception as e:
        logger.error('Error checking master status: {}', e)
        return False


async def process_change_data(ctx, change):
    """Process change data (only called by master worker)."""
    try:
        logger.debug('Processing change data: {}', change)

        await ctx['worker_data'].hincr('run_count')
        await ctx['worker_data'].set('last_run_at', int(time.time() * 1000))

        namespace = change.get('ns', {})
        collection_name = namespace.get('coll', 'unknown')
        operation_type = change.get('operationType', 'unknown')

        if operation_type not in ('insert', 'replace', 'update', 'delete'):
            logger.debug('Skip unsupported operation type: {}', operation_type)
            return
        
        # Get resume token and calculate change_id
        resume_token = change.get('_id')
        change_id = calculate_change_id_from_resume_token(resume_token)
        change['change_id'] = change_id
        
        doc_id = change.get('documentKey', {}).get('_id')
        if isinstance(doc_id, ObjectId):
            doc_id = str(doc_id)
            change['documentKey']['_id'] = doc_id
            if 'fullDocument' in change:
                change['fullDocument']['_id'] = doc_id
            if 'fullDocumentBeforeChange' in change:
                change['fullDocumentBeforeChange']['_id'] = doc_id

        bucket = get_bucket(doc_id, get_bucket_count(ctx))
        recv_key = get_recv_key(ctx, f'{collection_name}:{bucket}')

        cluster_time = change['clusterTime']
        score = cluster_time.time

        # Clean up metadata fields
        change.pop('_id', None)
        change.pop('clusterTime', None)

        await ctx[redis_major_label].zadd(recv_key, {orjson.dumps(change): score})

        logger.debug(
            'Added to zset: key={} score={}, operation={}, doc_id={}, change_id={}', 
            recv_key, score, operation_type, doc_id, change_id
        )

        # Notify when backlog is large or oldest item is stale
        try:
            await enqueue_notify(ctx, collection_name, bucket)
            # Save resume token for resuming from this position
            await save_resume_token(ctx, resume_token)
        except Exception as e:
            logger.warning('Notify enqueue failed: {}', e)

    except Exception as e:
        logger.error('Error processing change data: error={}, change={}', format_error(e), change)
