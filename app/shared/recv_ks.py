import time
import orjson 
import asyncio
import inspect
from aiokafka import AIOKafkaConsumer
from loguru import logger

from .config import custom_config
from .worker import healthcheck
from .api.utils import format_error


async def enqueue_job(ctx, queue_client, notify_queue, notify_entry, data):
    await ctx['worker_data'].hincr('run_count')
    await ctx['worker_data'].set('last_run_at', int(time.time() * 1000))

    logger.debug('Enqueue job: queue={} entry={} data={}', notify_queue, notify_entry, data)
    await queue_client.enqueue_job(notify_entry, data=data, _queue_name=notify_queue)


async def periodic_healthcheck(ctx, interval_seconds: int = 10):
    """Run worker healthcheck periodically in the background."""
    while True:
        try:
            await healthcheck(ctx, int(time.time() * 1000))
        except asyncio.CancelledError:
            logger.info('Healthcheck task cancelled')
            break
        except Exception as e:
            logger.warning('Healthcheck failed: {}', e)
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info('Healthcheck sleep cancelled')
            break


async def run(ctx):
    topic = ctx['kafka_topic']
    group = ctx['kafka_group']
    bootstrap_servers = ctx['kafka_bootstrap_servers']
    notify_queue = ctx['notify_queue']
    notify_entry = ctx['notify_entry']
    handle_event = ctx.get('handle_event', None)
    queue_client = ctx[custom_config.get_redis_queue_label()]
    consumer = None
    retry_count = 0
    max_retries = 10
    base_delay = 1  # seconds

    health_task = asyncio.create_task(periodic_healthcheck(ctx))
    try:
        while True:
            try:
                if consumer is None:
                    consumer = AIOKafkaConsumer(
                        topic, 
                        bootstrap_servers=bootstrap_servers,
                        group_id=group,
                    )
                    logger.info('Starting consumer for bootstrap servers: {}', bootstrap_servers)
                    await consumer.start()
                    
                    logger.info('Ready to consume {} in {}', topic, group)
                    retry_count = 0  # Reset retry count on successful connection

                async for msg in consumer:
                    try:
                        data = orjson.loads(msg.value)
                        if not isinstance(data, dict):
                            logger.warning('Unexpected message: {}', msg)
                            continue

                        skip = False
                        if handle_event:
                            try:
                                if inspect.iscoroutinefunction(handle_event):
                                    skip, data = await handle_event(ctx, data)
                                else:
                                    skip, data = handle_event(ctx, data)
                            except Exception as e:
                                logger.error('Error while handling event: {}', format_error(e))
                                continue

                        if not skip:
                            await enqueue_job(ctx, queue_client, notify_queue, notify_entry, data)
                    except Exception as e:
                        logger.error("Error while processing: {}", format_error(e))
                        continue

            except Exception as e:
                logger.error("Kafka connection error: {}", format_error(e))
                
                # Calculate delay with exponential backoff
                delay = min(base_delay * (2 ** retry_count), 300)  # Max 5 minutes
                retry_count += 1
                
                if retry_count >= max_retries:
                    logger.error("Max retries reached, exiting")
                    raise
                
                logger.info("Retrying in {} seconds... (attempt {}/{})", delay, retry_count, max_retries)
                
                # Close consumer if it exists
                if consumer is not None:
                    try:
                        await consumer.stop()
                    except Exception:
                        pass
                    consumer = None
                
                # Wait before retrying
                await asyncio.sleep(delay)
                
            except asyncio.CancelledError:
                logger.info('Stopping consumer')
                if consumer is not None:
                    await consumer.stop()
                break
    finally:
        if health_task and not health_task.done():
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass
