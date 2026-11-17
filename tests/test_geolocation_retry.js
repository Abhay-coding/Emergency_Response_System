const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/medical.js', 'utf8');
const start = source.indexOf('function requestDeviceLocation()');
const end = source.indexOf('\nasync function saveDetails', start);
assert(start >= 0 && end > start);

function setup(geolocation) {
  const elements = {'share-location': {disabled: false}, 'location-feedback': {textContent: ''}};
  const calls = [];
  const context = {
    state: {active: {id: 42}}, navigator: {geolocation}, window: {isSecureContext: true},
    $: id => elements[id], activeHeaders: () => ({'X-Alert-Token': 'test-token'}),
    setBusy: (button, busy) => {button.disabled = busy;}, toast() {},
    api: async (path, options) => {calls.push({path, options});}, refreshStudent: async () => {},
  };
  vm.runInNewContext(source.slice(start, end), context);
  return {context, elements, calls};
}

(async () => {
  let attempts = 0;
  const success = setup({getCurrentPosition(ok, fail, options) {
    assert.equal(options.timeout, 20000);
    if (++attempts === 1) fail({code: 3});
    else ok({coords: {latitude: 28.5, longitude: 77.2, accuracy: 50}});
  }});
  success.context.requestDeviceLocation();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(attempts, 2);
  assert.equal(success.calls.length, 1);
  assert.equal(success.calls[0].path, '/medical-alerts/42/location');
  assert.match(success.elements['location-feedback'].textContent, /saved/);

  let deniedAttempts = 0;
  const denied = setup({getCurrentPosition(ok, fail) {deniedAttempts++; fail({code: 1});}});
  denied.context.requestDeviceLocation();
  assert.equal(deniedAttempts, 1);
  assert.equal(denied.calls.length, 0);
  assert.match(denied.elements['location-feedback'].textContent, /denied/);

  let delayedSuccess;
  const changed = setup({getCurrentPosition(ok) {delayedSuccess = ok;}});
  changed.context.requestDeviceLocation();
  changed.context.state.active = {id: 43};
  await delayedSuccess({coords: {latitude: 28.5, longitude: 77.2, accuracy: 50}});
  assert.equal(changed.calls.length, 0);
  assert.equal(changed.elements['share-location'].disabled, false);
  console.log('Geolocation retry and alert isolation checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
