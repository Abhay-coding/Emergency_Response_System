const OFFLINE_DB = 'campus-medical-offline';
const ALERT_STORE = 'pending-alerts';
let databasePromise;

function openAlertDatabase() {
  if (!databasePromise) {
    databasePromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(OFFLINE_DB, 1);
      request.onupgradeneeded = () => {
        const store = request.result.createObjectStore(ALERT_STORE, {keyPath: 'idempotencyKey'});
        store.createIndex('status', 'status');
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    }).catch(error => {
      databasePromise = null;
      throw error;
    });
  }
  return databasePromise;
}

async function alertTransaction(mode, operation) {
  const database = await openAlertDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(ALERT_STORE, mode);
    const request = operation(transaction.objectStore(ALERT_STORE));
    transaction.oncomplete = () => resolve(request.result);
    transaction.onabort = () => reject(transaction.error);
  });
}

async function finishQueuedAlert(initial, status, result = null) {
  const database = await openAlertDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(ALERT_STORE, 'readwrite');
    const store = transaction.objectStore(ALERT_STORE);
    const request = store.get(initial.idempotencyKey);
    request.onsuccess = () => {
      const current = request.result;
      if (current?.status === 'pending_sync') store.put({...current, status, result});
    };
    transaction.oncomplete = resolve;
    transaction.onabort = () => reject(transaction.error);
  });
}

async function deliverAlert(alert) {
  if (!alert.apiUrl) return; // Entries from the original prototype have no verified destination.
  const configResponse = await fetch(alert.apiUrl + '/config', {cache: 'no-store'});
  if (!configResponse.ok) throw Error('Demo configuration is temporarily unavailable');
  const config = await configResponse.json();
  if (config.prototype !== true || (config.demo_mode !== true && config.browser_workflow !== 'sql')) {
    await finishQueuedAlert(alert, 'failed');
    return;
  }
  const response = await fetch(alert.apiUrl, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'Idempotency-Key': alert.idempotencyKey},
    body: JSON.stringify(alert.body),
  });
  if (response.ok) {
    const result = await response.json();
    if (!result.id || !result.guest_token) throw Error('Incomplete guest alert response');
    await finishQueuedAlert(alert, 'synced', result);
  } else if (response.status >= 400 && response.status < 500 && ![409, 429].includes(response.status)) {
    await finishQueuedAlert(alert, 'failed');
  } else {
    throw Error('Demo alert delivery will retry');
  }
}

globalThis.OfflineStorage = {
  storeAlert: alert => alertTransaction('readwrite', store => store.put(alert)),
  getAlert: key => alertTransaction('readonly', store => store.get(key)),
  getPendingAlerts: () => alertTransaction('readonly', store => store.index('status').getAll('pending_sync')),
  deleteAlert: key => alertTransaction('readwrite', store => store.delete(key)),
  deliverAlert,
};
