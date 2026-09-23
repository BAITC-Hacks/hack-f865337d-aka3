// Run with Node 22+: node tests/frontend.test.mjs
// State/transport tests with a minimal DOM double; this is NOT a visual browser test.
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';

export async function runFrontendTests() {
  const source = await readFile(new URL('../frontend/app.js', import.meta.url), 'utf8');
  const original = JSON.parse(await readFile(new URL('../docs/examples/profile.demo.json', import.meta.url), 'utf8'));
  const recs = JSON.parse(await readFile(new URL('../docs/examples/recommendations.demo.json', import.meta.url), 'utf8'));
  const after = JSON.parse(await readFile(new URL('../docs/examples/profile-after.demo.json', import.meta.url), 'utf8'));
  original.available_goals ||= []; original.history ||= []; original.completion_available = true;
  after.available_goals ||= []; after.history ||= []; after.completion_available = true;
  const elements = new Map(), storage = new Map(), requests = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, { value:'', innerHTML:'', textContent:'', disabled:false,
      classList:{add(){},remove(){},toggle(){}}, querySelectorAll(){return [];}, scrollIntoView(){}, focus(){},
      insertAdjacentHTML(position, html){ element('chat').innerHTML += html; } });
    return elements.get(id);
  };
  let current = original, fail = false, offline = false, gate;
  const api = {
    abort(){}, authConfig:async()=>({jury_demo:false,employees:[]}),
    me:async()=>({role:'employee',employee_id:element('employee').value || 'DEMO_001'}),
    login:async()=>({}), logout:async()=>({}),
    health:async()=>({demo:true}), profile:async()=>{if(offline) throw new Error('offline'); return structuredClone(current);},
    recommendations:async()=>structuredClone(recs),
    complete:async(id,event,attempt)=>{
      requests.push(structuredClone({id,event,attempt}));
      if(gate) await gate;
      if(fail) throw new Error('network failure');
      current = after;
      return {status:'completed',profile:original}; // Deliberately stale response, must GET.
    },
  };
  let uuid = 0;
  const context = vm.createContext({document:{getElementById:element,querySelectorAll:()=>[]},
    sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
    location:{origin:'http://test'}, crypto:{randomUUID:()=>`id-${++uuid}`},
    AbortController, createApi:()=>api, console });
  new vm.Script(source.replace(/^import .*;\r?\n/, '')).runInContext(context);
  const run = code => new vm.Script(code).runInContext(context);
  await run('initialize()');
  element('employee').value = 'DEMO_001'; element('token').value = 'test';
  await run('connect()');
  assert.match(element('profile').innerHTML,/60%/);
  assert.match(element('chat').innerHTML,/Три готовых вопроса/);
  assert.match(element('chat').innerHTML,/<textarea/);
  assert.match(element('chat').innerHTML,/Спросить/);
  const chatRequests = [];
  api.chat = async(id,body)=>{ chatRequests.push({id,body:structuredClone(body)}); return {message:'Развивайте навыки по выбранной цели.',source:'ai'}; };
  await run("sendChat('   ')");
  assert.equal(chatRequests.length,0);
  assert.match(element('chat-error').textContent,/Введите вопрос/);
  run("chatEvent = 'DEMO_DESIGN'");
  element('chat-input').value = 'Как подготовиться к новой роли?';
  let prevented = false;
  await element('chat-input').onkeydown({ctrlKey:true,key:'Enter',preventDefault(){prevented=true;}});
  assert.ok(prevented);
  assert.equal(chatRequests[0].id,'DEMO_001');
  assert.equal(chatRequests[0].body.message,'Как подготовиться к новой роли?');
  assert.equal(chatRequests[0].body.event_id,'DEMO_DESIGN');
  await run("sendChat('Какие навыки важнее?')");
  assert.equal(chatRequests[1].body.history.length,2);
  api.chat = async()=>{ throw new Error('offline'); };
  await run("sendChat('Мой вопрос для повтора')");
  assert.match(element('chat-error').textContent,/Попробуйте ещё раз/);
  assert.equal(run('chatDraft'),'Мой вопрос для повтора');
  // Loading blocks duplicate submissions and a late chat response cannot restore a logged-out session.
  let releaseChat;
  api.chat = async()=>{ await new Promise(resolve=>releaseChat=resolve); return {message:'Поздний ответ',source:'ai'}; };
  const lateChat = run("sendChat('Новый вопрос')");
  assert.match(element('chat').innerHTML,/Ожидание/);
  await run("sendChat('Двойной клик')");
  await run('logout()'); releaseChat(); await lateChat;
  assert.equal(element('chat').innerHTML,'');
  assert.equal(run('chatDraft'),'');
  element('token').value = 'test'; await run('connect()');
  fail = true;
  await run("complete('DEMO_DESIGN')");
  assert.match(element('pending').innerHTML,/Повторить запрос/);
  assert.equal(JSON.parse([...storage.values()][0]).DEMO_DESIGN.key, requests[0].attempt.key);
  fail = false;
  await run("complete('DEMO_DESIGN')");
  assert.deepEqual(requests[0].attempt,requests[1].attempt);
  assert.match(element('profile').innerHTML,/70%/);
  assert.deepEqual(JSON.parse([...storage.values()][0]),{});
  // A double click while awaiting the server sends only one request.
  let release; gate = new Promise(resolve=>release=resolve);
  const inFlight = run("complete('DEMO_DESIGN')");
  const count = requests.length;
  await run("complete('DEMO_DESIGN')"); assert.equal(requests.length,count);
  release(); await inFlight; gate = null;
  run("currentRecommendations.items.push({event_id:'REPEAT',repeatable:true})");
  await run("complete('REPEAT')");
  const firstParticipation = requests.at(-1).attempt.body.participation_id;
  run("currentRecommendations.items.push({event_id:'REPEAT',repeatable:true})");
  await run("complete('REPEAT')");
  assert.notEqual(requests.at(-1).attempt.body.participation_id,firstParticipation);
  // A server acknowledgement and failed follow-up GET must not become a generic failed completion.
  offline = true;
  await run("complete('DEMO_DESIGN')");
  assert.match(element('notice').innerHTML,/Выполнение сохранено, но обновление экрана не удалось/);
  offline = false;
  // Pending request survives creating a new app context (reload) and remains profile-scoped.
  fail = true; await run("complete('DEMO_DESIGN')");
  const savedKey = requests.at(-1).attempt.key;
  const reloaded = vm.createContext({
    document:{getElementById:element,querySelectorAll:()=>[]},
    sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
    location:{origin:'http://test'},crypto:{randomUUID:()=>`id-${++uuid}`},AbortController,createApi:()=>api,
  });
  new vm.Script(source.replace(/^import .*;\r?\n/, '')).runInContext(reloaded);
  await new vm.Script('initialize()').runInContext(reloaded);
  element('token').value = 'test';
  await new vm.Script('connect()').runInContext(reloaded);
  assert.match(element('pending').innerHTML,/Повторить запрос/);
  fail = false;
  await new vm.Script("complete('DEMO_DESIGN')").runInContext(reloaded);
  assert.equal(requests.at(-1).attempt.key,savedKey);
  api.me = async()=>({role:'employee',employee_id:'ANOTHER'});
  element('token').value = 'another'; await run('connect()');
  assert.equal(element('pending').innerHTML,'');
  // An old completion may finish after logout; no old profile, notices or chat may return.
  gate = new Promise(resolve=>release=resolve);
  const stale = run("complete('DEMO_DESIGN')");
  await run('logout()');
  release(); await stale; gate = null;
  assert.equal(element('profile').innerHTML,'');
  assert.equal(element('overview').innerHTML,'');
  assert.equal(element('chat').innerHTML,'');
  assert.match(element('notice').innerHTML,/Вы вышли/);
  assert.equal(element('employee-view').hidden,true);
  // Role selection cannot turn an employee code into an HR session.
  element('token').value = 'employee-code';
  run("selectedRole = 'hr'");
  await run('connect()');
  assert.match(element('notice').innerHTML,/Этот код принадлежит роли сотрудник/);
  assert.equal(element('session-panel').hidden,true);
  // A late HR response is also ignored after logout.
  api.me = async()=>({role:'hr',employee_id:null});
  api.overview = async()=>{ await new Promise(resolve=>release=resolve); return {}; };
  element('token').value = 'hr-code';
  const lateHr = run('connect()');
  await new Promise(resolve=>setImmediate(resolve));
  await run('logout()');
  release(); await lateHr;
  assert.equal(element('overview').innerHTML,'');
  assert.equal(element('profile').innerHTML,'');
  return 'Frontend state tests passed: retries, double click, persistence/isolation, fresh GET, saved-but-refresh-failed, logout and stale response rejection.';
}

if (typeof process !== 'undefined' && process.argv[1]?.replaceAll('\\','/').endsWith('/frontend.test.mjs')) console.log(await runFrontendTests());
