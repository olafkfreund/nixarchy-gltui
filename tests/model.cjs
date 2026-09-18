const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const model = {};
vm.createContext(model);
vm.runInContext(fs.readFileSync('ActionsModel.js', 'utf8'), model);
const repos = [{repo: 'owner/repo', runs: [{id: 7, status: 'in_progress', name: 'CI', head_branch: 'main', run_number: 3}]}];
const expanded = {'repo:owner/repo': true, 'owner/repo:7': true, 'owner/repo:7:8': true};
const details = {'owner/repo:7': {jobs: [{id: 8, name: 'build', status: 'in_progress', steps: [{number: 1, name: 'Checkout', status: 'completed', conclusion: 'success'}]}]}};
const rows = model.rows(repos, expanded, details, '', Date.now());
assert.equal(rows.length, 4);
assert.equal(rows[3].title, 'Checkout');
assert.equal(rows[3].status, 'success');
assert.equal(rows[2].info.startsWith('1/1 steps'), true);
assert.equal(model.selection(rows, 'owner/repo:7:8', 0), 2);
assert.equal(model.selection([], 'missing', 5), 0);
assert.equal(model.rows(repos, {}, details, '', Date.now()).length, 1);
assert.equal(model.rows(repos, {}, {}, 'main', Date.now()).length, 1);
assert.equal(model.rows(repos, expanded, details, 'missing', Date.now()).length, 0);
assert.equal(model.rows(repos, expanded, {}, '', Date.now())[2].title, 'Loading jobs…');
assert.equal(model.duration({started_at:'2026-01-01T00:00:00Z'}, Date.parse('2026-01-01T00:01:15Z')), '1m 15s');
assert.equal(model.icon('cancelled'), '⊘');
assert.equal(model.icon('failure'), '✕');
assert.equal(model.reply('{"repos":[]}', '', 0), '{"repos":[]}');
assert.equal(JSON.parse(model.reply('', 'python3: cannot open helper', 2)).error, 'python3: cannot open helper');
assert.equal(JSON.parse(model.reply('', '', 1)).error, 'Workflow helper returned no data (exit 1)');
const ranked = model.rows([{repo:'z/idle', checked:'now', active:0}, {repo:'a/unchecked'}, {repo:'b/running', active:2, checked:'now'}], {}, {}, '', Date.now());
assert.equal(ranked[0].title, 'b/running');
assert.equal(ranked[0].info, '2 running');
assert.equal(ranked[2].info, 'not checked');
assert.equal(model.rows([{repo:'a/b', description:'find this project'}], {}, {}, 'find this', Date.now()).length, 1);
const backing = [];
let edits = 0;
const list = {
  get count() { return backing.length; },
  get(i) { return backing[i]; },
  insert(i, value) { backing.splice(i, 0, value); edits++; },
  move(from, to) { backing.splice(to, 0, ...backing.splice(from, 1)); edits++; },
  remove(i, count) { backing.splice(i, count); edits++; },
  setProperty(i, role, value) { backing[i][role] = value; edits++; }
};
const first = [{key:'a',title:'A',status:'queued'}, {key:'b',title:'B',status:'queued'}];
assert.equal(model.syncRows(list, first), true);
const originalA = backing[0];
edits = 0;
assert.equal(model.syncRows(list, first), false);
assert.equal(edits, 0, 'Identical polling result must not reset or update delegates');
assert.equal(model.syncRows(list, [{...first[0],status:'in_progress'}, first[1]]), false);
assert.equal(backing[0], originalA, 'Status update preserves existing row');
assert.equal(model.syncRows(list, [first[1], first[0]]), true);
assert.equal(backing[1], originalA, 'Reordering moves the row instead of recreating it');
model.syncRows(list, [first[0]]);
assert.equal(list.count, 1);
assert.equal(backing[0].rowKey, 'a');
console.log('Model: hierarchy, filtering, progress, selection and duration passed');
