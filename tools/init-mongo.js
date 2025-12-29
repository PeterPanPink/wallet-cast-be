// MongoDB initialization script for local development.
// Creates demo databases with a marker document so they persist.
(() => {
  const databases = ['walletcast_demo'];

  databases.forEach((name) => {
    const database = db.getSiblingDB(name);

    if (database.getCollectionInfos({ name: '__init__' }).length === 0) {
      database.createCollection('__init__');
    }

    database.getCollection('__init__').updateOne(
      { _id: 'initialized' },
      { $set: { initializedAt: new Date().toISOString() } },
      { upsert: true }
    );
  });
})();
