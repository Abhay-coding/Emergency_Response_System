const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/config.js', 'utf8');
function load(host, search, stored) {
  const context = { URL, URLSearchParams, console: {log(){},warn(){}}, window: {location:{hostname:host,search,origin:`https://${host}`},localStorage:{getItem:()=>stored,setItem(){},removeItem(){}}} };
  vm.runInNewContext(source,context);
  return context.window.CER_CONFIG;
}
const production = load('example.github.io','?api_url=https%3A%2F%2Fattacker.example','https://attacker.example');
assert.equal(production.API_BASE_URL,'https://myypbjkalj.execute-api.ap-south-1.amazonaws.com');
assert.throws(()=>production.setApiUrl('https://attacker.example'));
assert.equal(load('127.0.0.1','?api_url=http%3A%2F%2F127.0.0.1%3A18080',null).API_BASE_URL,'http://127.0.0.1:18080');
assert.notEqual(load('127.0.0.1','?api_url=https%3A%2F%2Fattacker.example',null).API_BASE_URL,'https://attacker.example');
console.log('Frontend API override checks passed');
