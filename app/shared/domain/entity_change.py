import mmh3
import time
import uuid
from collections import defaultdict
from typing import Literal, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from random import randint
from loguru import logger

from ..config import custom_config
from ..storage.redis import get_redis_client
from ..storage.mongo import get_mongo_client


SNAPSHOT = 0
CHANGE_STREAM = 1

TASK_LEVEL_HIGH = 1
TASK_LEVEL_MEDIUM = 2
TASK_LEVEL_LOW = 3

utc_now = lambda: datetime.now(timezone.utc)
utc_now_ms = lambda: int(time.time() * 1000)
ms_to_dt = lambda ms: datetime.fromtimestamp(int(ms) / 1000, timezone.utc)
dt_to_ms = lambda dt: int(dt.timestamp() * 1000)


class Version(BaseModel):
    # Primary business version (decides apply/no-op): updated_at_ms or a monotonically increasing revision
    biz: int = Field(0, alias="b", description="Business version: updated_at_ms or monotonically increasing revision")

    # Unified logical timestamp (used only for tie-breaking & stable pagination): packed cluster_time/snapshot_time
    ts: int  = Field(0, alias="t", description="Logical timestamp sequence: packed cluster_time/snapshot_time")

    # Source priority for tie-breaking at the same ts (lower first): SNAPSHOT=0, CHANGE_STREAM=1
    src: int = Field(SNAPSHOT, alias="s", description="Source rank: SNAPSHOT=0, CHANGE_STREAM=1")

    # Index within the same ts/source: CHANGE_STREAM=txnOpIndex; SNAPSHOT=sequence number inside a snapshot epoch
    idx: int = Field(0, alias="i", description="Index sequence: txnOpIndex for CHANGE_STREAM; seq_no within snapshot epoch")

    model_config = ConfigDict(populate_by_name=True)


class EntityChange(BaseModel):
    # Bucket identifier (e.g., mmh3(entity_id) % MAX_BUCKET)
    bucket: int = Field(..., alias="bid")

    # Global idempotency key for this change
    change_id: str = Field(..., alias="cid")

    # Target entity identifier (e.g., user_id)
    entity_id: str = Field(..., alias="eid")

    # Version tuple used for ordering & CAS
    version: Version = Field(..., alias="ver")

    # Processing state of this change document
    status: Literal["wait", "done", "fail"] = Field("wait", alias="sts")
    
    # Change payload (full or delta)
    values: dict[str, Any] = Field(..., alias="val")
    
    # Document created time (UTC)
    created_at: datetime = Field(default_factory=utc_now, alias="crt")
    
    # Document updated time (UTC)
    updated_at: datetime = Field(default_factory=utc_now, alias="upd")

    # Per-document expiration time for TTL; set only for done/fail, keep None for wait
    expires_at: datetime | None = Field(None, alias="exp")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ChangeTask(BaseModel):
    # Bucket identifier (e.g., mmh3(entity_id) % MAX_BUCKET)
    bucket: int = Field(..., alias="bid")

    # Target entity identifier (e.g., user_id)
    entity_id: str = Field(..., alias="eid")

    # Priority level of this task, ranges from 1 to 3, 1 is the highest
    level: int = Field(0, alias="lvl")

    # Number of changes needed to be processed by this task
    count: int = Field(0, alias="cnt")

    # Latest change enqueued time (UTC)
    enqued_at: datetime = Field(default_factory=utc_now, alias="enq")

    # Latest change processed time (UTC)
    dequed_at: datetime | None = Field(None, alias="deq")

    # Per-document expiration time for TTL; set only for cnt = 0
    expires_at: datetime | None = Field(None, alias="exp")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


entity_change_params = {
    "indexes": [
        {
            "keys": [("bid", 1), ("eid", 1), ("ver.b", 1), ("ver.t", 1), ("ver.s", 1), ("ver.i", 1), ("_id", 1)],
            "partialFilterExpression": {"sts": "wait"},
            "name": "idx_entity_change_queue",
        },
        {"keys": [("bid", 1), ("eid", 1), ("cid", 1)], "unique": True},
        {"keys": [("exp", 1)], "expireAfterSeconds": 0},
    ],
    "shard_key": {"bid": 1, "eid": "hashed"}
}


change_task_params =  {
    "indexes": [
        {
            "keys": [("bid", 1), ("lvl", -1), ("deq", 1), ("enq", -1), ("cnt", -1), ("_id", -1), ("eid", 1)],
            "partialFilterExpression": {"cnt": {"$gt": 0}},
            "name": "idx_change_task_queue",
        },
        {"keys": [("bid", 1), ("eid", 1)], "unique": True},
        {
            "keys": [("bid", 1), ("lvl", 1)],
            "partialFilterExpression": {"cnt": {"$gt": 0}},
        },
        {"keys": [("exp", 1)], "expireAfterSeconds": 0},
    ],
    "shard_key": {"bid": 1}
}


def get_bucket(entity_id: str, bucket_size: int) -> int:
    return mmh3.hash(str(entity_id)) % bucket_size if bucket_size > 1 else 0


def get_change_id(entity_type: str, entity_id: str, epoch: int, seq: int) -> str:
    s = f'{entity_type}|{entity_id}|{epoch}|{seq}'
    # 128-bit MurmurHash3, formatted as 32-char hex string
    return format(mmh3.hash128(s), '032x')


async def get_cluster_ts(client: AsyncIOMotorClient) -> int:
    doc = await client.admin.command('ping')
    ct = doc.get("$clusterTime", {}).get("clusterTime")
    return (ct.time << 32) | (ct.inc & 0xFFFFFFFF) if ct else 0


async def get_tasks(mongo_label, task_name, bucket: int = 0, task_limit: int = 100):
    client = get_mongo_client(mongo_label)
    db = client.get_database()

    # Fair newest-first with anti-starvation using deq (last dequeued time)
    # Sort order matches index: lvl desc, deq asc (never/oldest first), then newest enq
    logger.debug('Get tasks (fair order): task_name={} bucket={} limit={}', task_name, bucket, task_limit)

    tasks = await db[task_name].find(
        {'bid': bucket, 'cnt': {'$gt': 0}},
        projection={'_id': 0, 'bid': 1, 'eid': 1, 'cnt': 1}
    ).sort([
        ('lvl', -1), ('deq', 1), ('enq', -1), ('cnt', -1), ('_id', -1),
    ]).limit(task_limit).hint([
        ('bid', 1), ('lvl', -1), ('deq', 1), ('enq', -1), ('cnt', -1), ('_id', -1), ('eid', 1),
    ]).to_list(length=task_limit)

    # Update dequeue timestamp for the selected tasks to enforce fairness
    if tasks:
        when = utc_now()
        eids = [t['eid'] for t in tasks]
        await db[task_name].update_many({'bid': bucket, 'eid': {'$in': eids}}, {'$set': {'deq': when}})

    logger.info('Found {} tasks (fair order): task_name={} bucket={}', len(tasks), task_name, bucket)
    return tasks


async def update_backlog(task_name: str, values: dict[str, int]):
    if not values:
        return

    logger.debug('Update backlog: task_name={} buckets={}', task_name, values.keys())    

    service_code = custom_config.get_service_code()
    redis_major_label = custom_config.get_redis_major_label()    
    redis_client = get_redis_client(redis_major_label)
    pipeline = redis_client.pipeline()

    keys = []
    for bucket, count in values.items():
        key = f'{service_code}:backlog:{task_name}:{bucket}'
        keys.append(key)
        pipeline.incr(key, count)
        pipeline.expire(key, 60 * 60 * 24)
        pipeline.get(key)

    res = await pipeline.execute()
    
    # For any key whose value <= 0 after increment, delete it (in a single pipeline)
    del_pipeline = redis_client.pipeline()
    delete_keys = []
    for i, key in enumerate(keys):
        # Each key contributed 3 commands: INCR, EXPIRE, GET. The GET result is at index i*3 + 2
        val = res[i * 3 + 2]
        try:
            v = int(val) if val is not None else 0
        except Exception:
            v = 0
        if v <= 0:
            del_pipeline.delete(key)
            delete_keys.append(key)

    if delete_keys:
        logger.debug('Remove backlog: task_name={} buckets={}', task_name, delete_keys)
        await del_pipeline.execute()


async def get_backlog_total(*task_names: str, bucket_count: int = 1):
    logger.debug('Summarize backlogs for: {}', task_names)

    service_code = custom_config.get_service_code()
    redis_major_label = custom_config.get_redis_major_label()    
    redis_client = get_redis_client(redis_major_label)
    pipeline = redis_client.pipeline()

    for task_name in task_names:
        for i in range(bucket_count):
            pipeline.get(f'{service_code}:backlog:{task_name}:{i}')
    
    res = await pipeline.execute()

    # Flattened results: index = ci * MAX_BUCKET + bi
    backlogs, idx = defaultdict(int), 0
    for task_name in task_names:
        for i in range(bucket_count):
            val = res[idx]
            if val:
                backlogs[task_name] = int(val)
            idx += 1

    return backlogs


class TransformError(Exception):
    pass


def get_action(change: dict) -> str:
    if change['ver']['s'] == SNAPSHOT:
        return 'snapshot'
    else:
        return change['val']['operationType']


def make_owner(job_id: str) -> str:
    return f"job:{job_id}:{uuid.uuid4().hex[:8]}"


def get_expires_at(days: int):
    return utc_now() + timedelta(hours=days * 24) + timedelta(seconds=randint(0, 1000))


def snake_case(s: str) -> str:
    out = []
    for ch in s:
        if ch.isupper():
            out.append('_')
            out.append(ch.lower())
        else:
            out.append(ch)
    res = ''.join(out)
    return res.lstrip('_')


async def update_entity_change(src_coll, bid, eid, cid, sts, *, err=None, etc=None, att=10) -> bool:
    # wait is pending for processing, done is successful, fail is failed with retry, dead is failed no retry
    if sts not in {'wait', 'done', 'fail', 'dead'}:
        raise ValueError(f'Invalid status: {sts}')

    def _log():
        if sts == 'done':
            logger.debug(
                'Update entity change: source={} bid={} eid={} cid={} sts={} err={} etc={}', 
                src_coll.name, bid, eid, cid, sts, err, etc
            )
        else:
            logger.warning(
                'Update entity change: source={} bid={} eid={} cid={} sts={} err={} etc={}', 
                src_coll.name, bid, eid, cid, sts, err, etc
            )

    update_doc = {'$set': {'upd': utc_now()}}
    if err:
        update_doc['$set']['err'] = err

    if etc:
        update_doc['$set']['etc'] = etc

    if att < 1 or att > 1000:
        att = 10

    if sts == 'fail':
        _log()
        # fail status not saved to db because entity_change has partial indexes on sts = 'wait',
        # there is no index on sts = 'fail', so rewrite it to wait and increment att
        update_doc['$set']['sts'] = 'wait'
        retry_doc = await src_coll.find_one({'bid': bid, 'eid': eid, 'cid': cid}, projection={'att': 1})
        if retry_doc and 'att' in retry_doc and retry_doc['att'] < att:
            update_doc['$inc'] = {'att': 1}
            await src_coll.update_one({'bid': bid, 'eid': eid, 'cid': cid}, update_doc)
            # is_retry is True when fail status is rewritten to wait and att is incremented
            return True
        else:
            update_doc['$set']['sts'] = 'dead'
            await src_coll.update_one({'bid': bid, 'eid': eid, 'cid': cid}, update_doc)
            # is_retry is False when max att is reached
            return False


    update_doc['$set']['sts'] = sts

    if sts == 'done':
        update_doc['$set']['exp'] = get_expires_at(90)

    _log()

    await src_coll.update_one({'bid': bid, 'eid': eid, 'cid': cid}, update_doc)

    # is_retry is False when sts in {done, dead}
    return False