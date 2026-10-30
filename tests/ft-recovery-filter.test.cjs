const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('never checked filter reconciles with the real evidence backlog counter', () => {
  const html = fs.readFileSync('docs/ft-recovery.html', 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const backlog = JSON.parse(fs.readFileSync('docs/lab/ft-backlog.json'));
  const nodes = new Map();
  function node() {
    return {value:'',textContent:'',children:[],addEventListener(){},
      append(...items){this.children.push(...items)},
      replaceChildren(...items){this.children=items}};
  }
  const document = {createElement: node, getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, node());
    return nodes.get(id);
  }};
  document.getElementById('filter').value = 'never';
  const context = vm.createContext({document,fetch:()=>new Promise(()=>{}),rows:backlog.overdue_games});
  vm.runInContext(script, context);
  vm.runInContext('games=rows;render()', context);
  const expected = backlog.overdue_games.filter(row=>row.last_checked_at==null).length;
  if (backlog.overdue_omitted === 0)
    assert.equal(expected, backlog.classification.past_due_never_checked);
  assert.equal(nodes.get('count').textContent, expected+' jogos encontrados');
  assert.equal(nodes.get('games').children.length, expected);
});
