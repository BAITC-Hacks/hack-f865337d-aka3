import { createApi } from './api.js';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const percent = value => value == null ? 'Не определено — выберите цель' : `${value}%`;
const statuses = { completed:'Выполнено', in_progress:'В процессе', declined:'Отказ', dropped:'Прервано', no_show:'Пропуск', overdue:'Просрочено' };
let api, employeeId, backendBase = '', generation = 0, currentProfile, currentRecommendations, busy = false, view = 'employee';
let chatMessages = [], chatEvent = null, chatBusy = false, chatController, chatDraft = '';
let identity = null, selectedRole = 'employee', juryDemo = false;
const skillName = id => currentProfile?.skill_names?.[id] || id;
function notice(message = '', error = false) { $('notice').innerHTML = message ? `<div class="message ${error ? 'error' : ''}">${esc(message)}</div>` : ''; }
function pendingKey() { return `cq.pending:${backendBase || location.origin}:${employeeId}`; }
function attempts() { try { return JSON.parse(sessionStorage.getItem(pendingKey()) || '{}'); } catch { return {}; } }
function saveAttempts(value) { sessionStorage.setItem(pendingKey(), JSON.stringify(value)); }
function table(headers, rows) { return rows.length ? `<div class="table-wrap"><table><thead><tr>${headers.map(h => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>` : '<p class="muted">Нет записей.</p>'; }
function setBusy(value) {
  busy = value;
  document.querySelectorAll('#login-panel button,#login-panel select,#connect input,#connect button,#profile button,#profile select,#import-form input,#import-form button,nav button').forEach(el => el.disabled = value);
  if (!value && currentProfile && !currentProfile.completion_available) document.querySelectorAll('[data-complete]').forEach(el => el.disabled = true);
  if (!value && currentProfile && !currentProfile.available_goals.length) $('goal-form')?.querySelectorAll('button,select').forEach(el => el.disabled = true);
}
function completionButton(event, pid) { return `<button data-complete="${esc(event)}" ${pid ? `data-pid="${esc(pid)}"` : ''} ${!currentProfile.completion_available ? 'disabled' : ''}>Выполнить — демо</button>`; }
function renderProfile() {
  const p = currentProfile, r = currentRecommendations;
  const skills = [...new Set([...Object.keys(p.target_requirements), ...Object.keys(p.skills)])];
  const rows = skills.map(skill => {
    const gap = p.gaps.find(g => g.skill_id === skill), required = p.target_requirements[skill];
    const status = gap ? gap.critical ? 'Критический разрыв' : 'Нужно развить' : required == null ? 'Вне требований цели' : 'Требование покрыто';
    return `<tr class="${gap?.critical ? 'critical' : ''}"><td>${esc(skillName(skill))}<br><small>${esc(skill)}</small></td><td>${esc(p.skills[skill] ?? 0)}</td><td>${esc(required ?? '—')}</td><td>${status}</td></tr>`;
  });
  $('profile').innerHTML = `<article><div class="profile-head"><div><p class="eyebrow">ПРОФИЛЬ · ${esc(p.employee_id)}</p><h2>${esc(p.name)}</h2><p>${esc(p.role)} / ${esc(p.grade)}</p><small>Дата симуляции: ${esc(p.as_of)}<br>Последняя оценка: ${esc(p.last_review_date)}</small></div><div class="goal"><small>КАРЬЕРНАЯ ЦЕЛЬ</small><h3>${p.target ? `${esc(p.target.role)} / ${esc(p.target.grade)}` : 'Цель не выбрана'}</h3><span class="badge">${p.target_status === 'suggested' ? 'Предложена системой' : p.target_status === 'selected' ? 'Выбрана сотрудником' : 'Требуется выбор'}</span><form id="goal-form"><label>Выбрать цель<select id="goal">${p.available_goals.map((g,i) => `<option value="${i}" ${g.role === p.target?.role && g.grade === p.target?.grade ? 'selected' : ''}>${esc(g.role)} / ${esc(g.grade)}</option>`).join('')}</select></label><button ${p.available_goals.length ? '' : 'disabled'}>Сохранить цель</button></form></div></div><p>Покрытие требований по навыкам</p><div class="coverage">${percent(p.progress_percent)}</div>${p.progress_percent == null ? '' : `<progress max="100" value="${p.progress_percent}" aria-label="Покрытие требований по навыкам"></progress>`}</article>
  <article><h2>Навыки и разрывы</h2>${table(['Навык','Сейчас','Требуется','Статус'], rows)}</article>
  <div class="section-heading"><h2>Ваш следующий шаг</h2><button class="secondary" id="refresh">Обновить данные</button></div><p class="muted">Алгоритм выбирает допустимые шаги, AI объясняет их на данных сотрудника. Эффекты карточек не суммируются. «Выполнить — демо» симулирует завершение на дату среза.</p>
  ${p.completion_message ? `<div class="message error">${esc(p.completion_message)}</div>` : ''}
  <div id="pending"></div>
  ${r ? r.items.length ? `<div class="cards">${r.items.map((item,i) => `<article class="card"><small>ШАГ ${i+1} · ${item.format === 'self_paced' ? 'В своём темпе' : 'По расписанию'}${item.repeatable ? ' · Можно повторять' : ''}</small><h3>${esc(item.title)}</h3>${item.facts.eligible_session_date ? `<small>Дата: ${esc(item.facts.eligible_session_date)}</small>` : ''}<p>${esc(item.description || "")}</p>${item.duration_hours ? `<small>${item.duration_hours} ч · ${esc(item.original_format || item.format)}</small>` : ""}<p>${esc(item.explanation)}</p><small>Источник: ${item.explanation_source === 'ai' ? 'AI-объяснение' : 'Правила сервера (без AI)'}</small><ul>${item.expected_skill_changes.map(c => `<li>${esc(skillName(c.skill_id))}: ${c.before} → ${c.after} (ожидается)</li>`).join('')}</ul><div class="forecast">Ожидаемое покрытие после: <strong>${percent(item.progress_after)}</strong></div><div class="actions">${completionButton(item.event_id)}<button class="secondary" data-ask="${esc(item.event_id)}">Почему этот шаг?</button></div></article>`).join('')}</div>` : `<div class="empty">${esc(r.message || 'Рекомендаций пока нет.')}</div>` : '<div class="empty">Рекомендации не загружены. Нажмите «Обновить данные».</div>'}
  <article><h2>История и текущие активности</h2>${table(['Активность','Дата','Статус','Действие'], [...p.history].reverse().map(h => `<tr><td>${esc(h.title)}<br><small>${esc(h.participation_id)}</small></td><td>${esc(h.date)}</td><td>${esc(statuses[h.status] || h.status)}</td><td>${h.status === 'in_progress' ? completionButton(h.event_id,h.participation_id) : '—'}</td></tr>`))}</article>`;
  const pending = Object.entries(attempts());
  $('pending').innerHTML = pending.length ? `<article><h3>Запросы с неподтверждённым результатом</h3><p>Повтор использует прежние идентификаторы и не начислит результат дважды.</p>${pending.map(([event]) => `<p>${esc(event)} <button data-retry="${esc(event)}">Повторить запрос</button></p>`).join('')}</article>` : '';
  $('goal-form').onsubmit = saveGoal;
  $('refresh').onclick = async () => { const epoch = generation; setBusy(true); notice(); try { await refresh(epoch); } catch(e) { if(epoch === generation) notice(e.message,true); } finally { if(epoch === generation) setBusy(false); } };
  $('profile').querySelectorAll('[data-complete],[data-retry]').forEach(button => button.onclick = () => complete(button.dataset.complete || button.dataset.retry, button.dataset.pid));
  $('profile').querySelectorAll('[data-ask]').forEach(button => button.onclick = () => { chatEvent = button.dataset.ask; renderChat(); $('chat').scrollIntoView({ behavior:'smooth' }); });
}
async function refresh(epoch) {
  const client = api, id = employeeId;
  const recPromise = client.recommendations(id).then(value => ({value}), error => ({error}));
  const p = await client.profile(id);
  if (epoch !== generation) return;
  currentProfile = p;
  currentRecommendations = null;
  renderProfile();
  renderChat();
  const r = await recPromise;
  if (epoch !== generation) return;
  currentRecommendations = r.value || null;
  renderProfile();
  if (r.error) throw new Error(`Профиль загружен, но рекомендации недоступны: ${r.error.message}`);
}
function clearSession() {
  ++generation; api?.abort(); chatController?.abort();
  identity = null; currentProfile = null; currentRecommendations = null; employeeId = '';
  chatMessages = []; chatEvent = null; chatBusy = false; chatDraft = ''; busy = false;
  for (const id of ['profile','overview','chat','import-result','notice']) $(id).innerHTML = '';
  $('token').value = ''; $('employee').value = '';
  $('current-role').textContent = '';
  $('import-file').value = ''; $('history-file').value = '';
  $('session-panel').hidden = true; $('navigation').hidden = true;
  $('employee-view').hidden = true; $('hr-view').hidden = true; $('login-panel').hidden = false;
  api = createApi('', '');
}
async function enterSession(who, epoch) {
  if (epoch !== generation) return;
  identity = who;
  employeeId = who.employee_id || '';
  $('employee').value = employeeId;
  $('token').value = '';
  $('login-panel').hidden = true; $('session-panel').hidden = false; $('navigation').hidden = false;
  $('current-role').textContent = who.role === 'hr' ? 'Текущая роль: HR' : `Сотрудник · ${employeeId}`;
  $('hr-tab').hidden = who.role !== 'hr';
  view = who.role === 'hr' ? 'hr' : 'employee';
  $('employee-view').hidden = view !== 'employee'; $('hr-view').hidden = view !== 'hr';
  $('employee-tab').classList.toggle('selected', view === 'employee'); $('hr-tab').classList.toggle('selected', view === 'hr');
  if (view === 'hr') await loadHr(epoch); else await refresh(epoch);
}
async function connect(useDemo = false) {
  if (busy) return;
  const token = $('token').value.trim(), chosenEmployee = $('demo-employee').value;
  clearSession(); const epoch = generation;
  api = createApi('', useDemo ? '' : token);
  setBusy(true);
  try {
    if (!useDemo && !token) throw new Error('Введите код доступа к Career Quest.');
    const who = useDemo ? await api.demoLogin({role:selectedRole, employee_id:selectedRole === 'employee' ? chosenEmployee : null}) : await api.me();
    if(epoch !== generation) return;
    if(who.role !== selectedRole) throw new Error(`Этот код принадлежит роли ${who.role === 'hr' ? 'HR' : 'сотрудник'}. Выберите соответствующую карточку.`);
    if(!useDemo) await api.login();
    if(epoch !== generation) return;
    api.abort(); api = createApi('', '');
    await enterSession(who, epoch);
  }
  catch(e) { if(epoch === generation) notice(e.message,true); }
  finally { if(epoch === generation) setBusy(false); }
  checkHealth();
}
async function logout() {
  clearSession(); const epoch = generation; setBusy(true);
  try { await createApi('', '').logout(); if(epoch === generation) notice('Вы вышли. Выберите роль для нового входа.'); }
  catch(e) { if(epoch === generation) notice(`Данные экрана очищены, но выход на сервере не подтверждён. Повторите выход: ${e.message}`, true); }
  finally { if(epoch === generation) setBusy(false); }
}
async function complete(event, pid) {
  if (busy) return;
  const epoch = generation; let acknowledged = false;
  setBusy(true); notice('Сохраняем выполнение…');
  try {
    const all = attempts();
    if (!all[event]) {
      const repeatable = currentRecommendations?.items.find(x => x.event_id === event)?.repeatable;
      all[event] = { key:crypto.randomUUID(), body:pid ? { participation_id:pid } : repeatable ? { participation_id:crypto.randomUUID() } : {} };
      // Persist before sending; if storage is unavailable, do not issue an unsafe request.
      saveAttempts(all);
    }
    const result = await api.complete(employeeId,event,all[event]);
    if(epoch !== generation) return;
    acknowledged = true;
    delete all[event]; saveAttempts(all);
    await refresh(epoch);
    if(epoch !== generation) return;
    notice(result.status === 'already_completed' ? 'Участие уже было выполнено. Загружено актуальное состояние; повторного начисления нет.' : 'Выполнение сохранено. Навыки, история и рекомендации обновлены.');
  } catch(e) {
    if(epoch !== generation) return;
    if (!acknowledged && e.status >= 400 && e.status < 500 && ![408,425,429].includes(e.status)) {
      const all = attempts(); delete all[event]; saveAttempts(all);
    }
    notice(acknowledged ? `Выполнение сохранено, но обновление экрана не удалось. Нажмите «Обновить данные». ${e.message}` : e.message, true);
    if(currentProfile) renderProfile();
  } finally { if(epoch === generation) setBusy(false); }
}
async function saveGoal(event) {
  event.preventDefault(); if(busy) return;
  const goal = currentProfile.available_goals[Number($('goal').value)]; if(!goal) return;
  const epoch = generation; setBusy(true); let saved = false;
  try { await api.goal(employeeId,{role:goal.role,grade:goal.grade}); if(epoch !== generation) return; saved = true; await refresh(epoch); if(epoch === generation) notice('Карьерная цель сохранена.'); }
  catch(e) { if(epoch === generation) notice(`${saved ? 'Цель сохранена, обновите экран. ' : ''}${e.message}`,true); }
  finally { if(epoch === generation) setBusy(false); }
}
async function loadHr(epoch = generation) {
  $('overview').innerHTML = '<div class="empty">Загрузка HR-данных…</div>';
  try {
    const data = await api.overview(); if(epoch !== generation) return;
    const open = id => `<button class="secondary" data-open="${esc(id)}">${esc(id)}</button>`;
    $('overview').innerHTML = `<div class="section-heading"><h2>Развитие команды</h2><button class="secondary" id="refresh-hr">Обновить HR</button></div><p>${data.employees_count} сотрудников · На ${esc(data.as_of)}</p><article><h3>Открыть профиль сотрудника</h3><form id="hr-employee-form"><label>Сотрудник<select id="hr-employee-select">${data.participation.map(x=>`<option value="${esc(x.employee_id)}">${esc(x.employee_id)} · ${esc(x.name)}</option>`).join('')}</select></label><button ${data.participation.length ? '' : 'disabled'}>Открыть профиль</button><a href="#import-form">Загрузить проверочные профили</a></form></article><article><h3>Частые дефициты навыков</h3>${table(['Навык','Сотрудников с разрывом','С критическим разрывом'],data.skill_deficits.map(x=>`<tr><td>${esc(x.name || x.skill_id)}</td><td>${x.employees_count}</td><td>${x.critical_count}</td></tr>`))}</article><article><h3>Без подходящего следующего шага</h3>${table(['Сотрудник','Имя','Причина'],data.without_next_step.map(x=>`<tr><td>${open(x.employee_id)}</td><td>${esc(x.name)}</td><td>${esc(x.reason)}</td></tr>`))}</article><article><h3>Участие по мероприятиям</h3>${table(['Мероприятие','Завершено','В процессе','Отказы / пропуски','Просрочено'],(data.event_participation || []).map(x=>`<tr><td>${esc(x.title)}</td><td>${x.completed}</td><td>${x.in_progress}</td><td>${x.missed}</td><td>${x.overdue}</td></tr>`))}</article><article><h3>Сотрудники и участие</h3>${table(['Сотрудник','Имя','Завершено','В процессе','Отказы / пропуски'],data.participation.map(x=>`<tr><td>${open(x.employee_id)}</td><td>${esc(x.name)}</td><td>${x.completed}</td><td>${x.in_progress}</td><td>${x.missed}</td></tr>`))}</article>`;
    $('refresh-hr').onclick = () => switchView('hr');
    $('hr-employee-form').onsubmit = event => { event.preventDefault(); openEmployee($('hr-employee-select').value); };
    $('overview').querySelectorAll('[data-open]').forEach(b => b.onclick = () => openEmployee(b.dataset.open));
  } catch(e) { if(epoch !== generation) return; $('overview').innerHTML = `<div class="empty">${esc(e.status === 401 ? 'Требуется вход. Смените пользователя.' : e.status === 403 ? 'Требуются права HR. Смените пользователя.' : 'Не удалось загрузить сводку. Проверьте соединение и повторите.')} <button id="retry-hr">Повторить</button></div>`; $('retry-hr').onclick = () => switchView('hr'); throw e; }
}
async function switchView(next) {
  if(busy) return;
  if(next === 'hr' && identity?.role !== 'hr') { notice('Для HR-сводки смените пользователя.',true); return; }
  if(next === 'employee' && !employeeId) { notice('Откройте сотрудника из HR-сводки.'); return; }
  const epoch = generation;
  view = next; $('employee-view').hidden = next !== 'employee'; $('hr-view').hidden = next !== 'hr';
  $('employee-tab').classList.toggle('selected',next === 'employee'); $('hr-tab').classList.toggle('selected',next === 'hr'); notice();
  if(!api) { notice('Сначала введите ключ доступа и подключитесь.'); return; }
  setBusy(true);
  try { if(next === 'hr') await loadHr(); else await refresh(generation); }
  catch(e) { if(epoch === generation) notice(e.message,true); }
  finally { if(epoch === generation) setBusy(false); }
}
function openEmployee(id) {
  if(busy || identity?.role !== 'hr') return;
  ++generation; api.abort(); api = createApi('', ''); chatController?.abort();
  employeeId = id; $('employee').value = id; currentProfile = null; currentRecommendations = null;
  chatMessages = []; chatEvent = null; chatBusy = false; chatDraft = ''; $('chat').innerHTML = ''; $('profile').innerHTML = '<div class="empty">Загрузка…</div>';
  switchView('employee');
}
$('import-form').onsubmit = async event => {
  event.preventDefault(); if(busy || !api) return;
  const file = $('import-file').files[0], historyFile = $('history-file').files[0];
  if(!file && !historyFile) { notice('Выберите JSON профилей и/или CSV истории.',true); return; }
  const epoch = generation;
  setBusy(true); $('import-result').textContent = 'Проверка и загрузка файлов…'; let saved = false;
  try {
    if((file?.size || 0) + (historyFile?.size || 0) > 2*1024*1024) throw new Error('Файлы больше 2 МБ.');
    let body = {};
    if(file) { try { body = JSON.parse((await file.text()).replace(/^\uFEFF/,'')); } catch { throw new Error('Некорректный JSON профилей.'); } }
    if(Array.isArray(body)) body = {employees:body};
    if(historyFile) body.history_csv = await historyFile.text();
    if(epoch !== generation) return;
    const result = await api.importProfiles(body); saved = true;
    if(epoch !== generation) return;
    $('import-result').innerHTML = `<p>Импортировано профилей: ${result.employees_imported}; записей истории: ${result.history_imported}.</p>${result.employee_ids.map(id=>`<button class="secondary" data-open="${esc(id)}">Открыть ${esc(id)}</button>`).join(' ')}`;
    $('import-result').querySelectorAll('[data-open]').forEach(b => b.onclick = () => openEmployee(b.dataset.open));
    currentProfile = null; currentRecommendations = null; $('profile').innerHTML = ''; $('chat').innerHTML = ''; chatMessages = [];
    await loadHr(epoch); if(epoch === generation) { notice('Импорт сохранён, HR-данные обновлены.'); checkHealth(); }
  } catch(e) { if(epoch !== generation) return; if(!saved) $('import-result').textContent = e.message; notice(saved ? `Импорт сохранён, но HR не обновился: ${e.message}` : e.message,true); }
  finally { if(epoch === generation) setBusy(false); }
};
function renderChat() {
  $('chat').innerHTML = `<article class="chat"><h2>Карьерный помощник</h2><p>Три готовых вопроса помогут разобрать актуальные рекомендации. Помощник объясняет факты и не меняет профиль.</p>${chatEvent ? `<p>Активность: <strong>${esc(chatEvent)}</strong> <button class="secondary" id="clear-event">Общий вопрос</button></p>` : ''}<div class="chat-log" role="log">${chatMessages.map(m=>`<p><strong>${m.role === 'user' ? 'Вы' : 'Помощник'}</strong>${esc(m.content)}</p>`).join('')}</div><div class="chat-prompts">${['Почему этот шаг?','Что дальше?','Какие есть альтернативы?'].map(q=>`<button class="secondary" data-prompt="${esc(q)}" ${chatBusy || !currentProfile ? 'disabled' : ''}>${q}</button>`).join('')}</div>${chatBusy ? '<p>Готовим объяснение…</p>' : ''}<p id="chat-error" role="alert"></p></article>`;
  if($('clear-event')) $('clear-event').onclick = () => { chatEvent = null; renderChat(); };
  $('chat-error').insertAdjacentHTML('beforebegin', `<form id="chat-form" novalidate><label>Ваш вопрос<textarea id="chat-input" rows="3" maxlength="2000" aria-describedby="chat-hint chat-error" ${chatBusy || !currentProfile ? 'disabled' : ''} placeholder="Какие навыки мне стоит развить для моей цели?">${esc(chatDraft)}</textarea><small id="chat-hint">О профиле, навыках и карьерной цели · до 2000 символов · Ctrl+Enter для отправки</small></label><button ${chatBusy || !currentProfile ? 'disabled' : ''}>${chatBusy ? 'Ожидание…' : 'Спросить'}</button></form>`);
  $('chat-input').oninput = () => { chatDraft = $('chat-input').value; };
  $('chat-form').onsubmit = e => { e.preventDefault(); return sendChat($('chat-input').value); };
  $('chat-input').onkeydown = e => { if(e.ctrlKey && e.key === 'Enter' && !e.isComposing) { e.preventDefault(); return sendChat($('chat-input').value); } };
  $('chat').querySelectorAll('[data-prompt]').forEach(b => b.onclick = () => sendChat(b.dataset.prompt));
}
async function sendChat(message) {
  if(chatBusy || !currentProfile) return;
  message = message.trim();
  if(!message) { $('chat-error').textContent = 'Введите вопрос.'; $('chat-input').focus(); return; }
  if(message.length > 2000) { $('chat-error').textContent = 'Вопрос должен быть не длиннее 2000 символов.'; return; }
  const epoch = generation, history = chatMessages.slice(-20);
  chatMessages.push({role:'user',content:message}); chatDraft = ''; chatBusy = true; chatController = new AbortController(); renderChat();
  try {
    const response = await api.chat(employeeId,{message,event_id:chatEvent,history},chatController.signal);
    if(epoch !== generation) return;
    if(typeof response.message !== 'string') throw new Error('Некорректный ответ чата.');
    chatMessages.push({role:'assistant',content:response.message + (response.source === 'ai' ? '\nИсточник: AI' : '\nИсточник: правила сервера (без AI)')});
    chatMessages = chatMessages.slice(-20);
  } catch(e) { if(epoch === generation) { chatBusy = false; chatMessages.pop(); chatDraft = message; renderChat(); $('chat-error').textContent = `Не удалось отправить вопрос. Попробуйте ещё раз. ${e.message}`; return; } }
  finally { if(epoch === generation) chatBusy = false; }
  if(epoch === generation) renderChat();
}
async function checkHealth() {
  const epoch = generation;
  try { const h = await (api || createApi('', '')).health(); if(epoch === generation) { $('health').textContent = h.data_source === 'organizer_synthetic' ? `Датасет организаторов · ${h.employees_count} сотрудников` : h.demo ? 'Малый демонабор' : h.dataset_loaded ? 'Сервер подключён' : 'Данные не загружены'; } }
  catch { if(epoch === generation) $('health').textContent = 'Сервер недоступен'; }
}
$('connect').onsubmit = e => { e.preventDefault(); connect(); };
async function chooseRole(role) {
  if(busy) return;
  selectedRole = role;
  $('selected-role').textContent = `Выбрана роль: ${role === 'hr' ? 'HR' : 'сотрудник'}`;
  if(juryDemo) await connect(true); else $('token').focus();
}
$('login-employee').onclick = () => chooseRole('employee');
$('login-hr').onclick = () => chooseRole('hr');
$('logout').onclick = logout;
$('employee-tab').onclick = () => switchView('employee'); $('hr-tab').onclick = () => switchView('hr');
async function initialize() {
  api = createApi('', ''); const epoch = generation; setBusy(true);
  try {
    const config = await api.authConfig(); if(epoch !== generation) return;
    juryDemo = config.jury_demo;
    $('jury-banner').hidden = !juryDemo; $('demo-picker').hidden = !juryDemo; $('connect').hidden = juryDemo;
    $('demo-employee').innerHTML = config.employees.map(e => `<option value="${esc(e.employee_id)}">${esc(e.employee_id)} · ${esc(e.name)} · ${esc(e.role)} / ${esc(e.grade)}</option>`).join('');
    try { const who = await api.me(); await enterSession(who, epoch); }
    catch(e) { if(epoch === generation && e.status !== 401) notice(e.message,true); }
  } catch(e) { if(epoch === generation) notice(e.message,true); }
  finally { if(epoch === generation) setBusy(false); }
  checkHealth();
}
initialize();
