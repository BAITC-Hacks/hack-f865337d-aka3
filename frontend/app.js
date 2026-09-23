import { createApi } from './api.js';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const percent = value => value == null ? 'Не определено — выберите цель' : `${value}%`;
const statuses = { completed:'Выполнено', in_progress:'В процессе', declined:'Отказ', dropped:'Прервано', no_show:'Пропуск' };
let api, employeeId, backendBase = '', generation = 0, currentProfile, currentRecommendations, busy = false, view = 'employee';
let chatMessages = [], chatEvent = null, chatBusy = false, chatController;
// Enable only after the proposed server endpoint is implemented. No model keys here.
const CHAT_ENABLED = false;
function notice(message = '', error = false) { $('notice').innerHTML = message ? `<div class="message ${error ? 'error' : ''}">${esc(message)}</div>` : ''; }
function pendingKey() { return `cq.pending:${backendBase || location.origin}:${employeeId}`; }
function attempts() { try { return JSON.parse(sessionStorage.getItem(pendingKey()) || '{}'); } catch { return {}; } }
function saveAttempts(value) { sessionStorage.setItem(pendingKey(), JSON.stringify(value)); }
function table(headers, rows) { return rows.length ? `<div class="table-wrap"><table><thead><tr>${headers.map(h => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>` : '<p class="muted">Нет записей.</p>'; }
function setBusy(value) {
  busy = value;
  document.querySelectorAll('#connect input,#connect button,#profile button,#profile select,#import-form input,#import-form button,nav button').forEach(el => el.disabled = value);
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
    return `<tr class="${gap?.critical ? 'critical' : ''}"><td>${esc(skill)}</td><td>${esc(p.skills[skill] ?? 0)}</td><td>${esc(required ?? '—')}</td><td>${status}</td></tr>`;
  });
  $('profile').innerHTML = `<article><div class="profile-head"><div><p class="eyebrow">ПРОФИЛЬ · ${esc(p.employee_id)}</p><h2>${esc(p.name)}</h2><p>${esc(p.role)} / ${esc(p.grade)}</p><small>Дата симуляции: ${esc(p.as_of)}<br>Последняя оценка: ${esc(p.last_review_date)}</small></div><div class="goal"><small>КАРЬЕРНАЯ ЦЕЛЬ</small><h3>${p.target ? `${esc(p.target.role)} / ${esc(p.target.grade)}` : 'Цель не выбрана'}</h3><span class="badge">${p.target_status === 'suggested' ? 'Предложена системой' : p.target_status === 'selected' ? 'Выбрана сотрудником' : 'Требуется выбор'}</span><form id="goal-form"><label>Выбрать цель<select id="goal">${p.available_goals.map((g,i) => `<option value="${i}" ${g.role === p.target?.role && g.grade === p.target?.grade ? 'selected' : ''}>${esc(g.role)} / ${esc(g.grade)}</option>`).join('')}</select></label><button ${p.available_goals.length ? '' : 'disabled'}>Сохранить цель</button></form></div></div><p>Покрытие требований по навыкам</p><div class="coverage">${percent(p.progress_percent)}</div>${p.progress_percent == null ? '' : `<progress max="100" value="${p.progress_percent}" aria-label="Покрытие требований по навыкам"></progress>`}</article>
  <article><h2>Навыки и разрывы</h2>${table(['Навык','Сейчас','Требуется','Статус'], rows)}</article>
  <div class="section-heading"><h2>Ваш следующий шаг</h2><button class="secondary" id="refresh">Обновить данные</button></div><p class="muted">Каждый прогноз рассчитан отдельно от текущих навыков. Эффекты карточек не суммируются.</p>
  ${p.completion_message ? `<div class="message error">${esc(p.completion_message)}</div>` : ''}
  <div id="pending"></div>
  ${r ? r.items.length ? `<div class="cards">${r.items.map((item,i) => `<article class="card"><small>ШАГ ${i+1} · ${item.format === 'self_paced' ? 'В своём темпе' : 'По расписанию'}${item.repeatable ? ' · Можно повторять' : ''}</small><h3>${esc(item.title)}</h3>${item.facts.eligible_session_date ? `<small>Дата: ${esc(item.facts.eligible_session_date)}</small>` : ''}<p>${esc(item.explanation)}</p><small>Источник: ${item.explanation_source === 'ai' ? 'AI-объяснение' : 'Правила сервера (без AI)'}</small><ul>${item.expected_skill_changes.map(c => `<li>${esc(c.skill_id)}: ${c.before} → ${c.after} (ожидается)</li>`).join('')}</ul><div class="forecast">Ожидаемое покрытие после: <strong>${percent(item.progress_after)}</strong></div><div class="actions">${completionButton(item.event_id)}<button class="secondary" data-ask="${esc(item.event_id)}">Почему этот шаг?</button></div></article>`).join('')}</div>` : `<div class="empty">${esc(r.message || 'Рекомендаций пока нет.')}</div>` : '<div class="empty">Рекомендации не загружены. Нажмите «Обновить данные».</div>'}
  <article><h2>История и текущие активности</h2>${table(['Активность','Дата','Статус','Действие'], [...p.history].reverse().map(h => `<tr><td>${esc(h.title)}<br><small>${esc(h.participation_id)}</small></td><td>${esc(h.date)}</td><td>${esc(statuses[h.status] || h.status)}</td><td>${h.status === 'in_progress' ? completionButton(h.event_id,h.participation_id) : '—'}</td></tr>`))}</article>`;
  const pending = Object.entries(attempts());
  $('pending').innerHTML = pending.length ? `<article><h3>Запросы с неподтверждённым результатом</h3><p>Повтор использует прежние идентификаторы и не начислит результат дважды.</p>${pending.map(([event]) => `<p>${esc(event)} <button data-retry="${esc(event)}">Повторить запрос</button></p>`).join('')}</article>` : '';
  $('goal-form').onsubmit = saveGoal;
  $('refresh').onclick = async () => { setBusy(true); notice(); try { await refresh(generation); } catch(e) { notice(e.message,true); } finally { setBusy(false); } };
  $('profile').querySelectorAll('[data-complete],[data-retry]').forEach(button => button.onclick = () => complete(button.dataset.complete || button.dataset.retry, button.dataset.pid));
  $('profile').querySelectorAll('[data-ask]').forEach(button => button.onclick = () => { chatEvent = button.dataset.ask; renderChat(); $('chat').scrollIntoView({ behavior:'smooth' }); });
}
async function refresh(epoch) {
  const [p,r] = await Promise.allSettled([api.profile(employeeId), api.recommendations(employeeId)]);
  if (epoch !== generation) return;
  if (p.status === 'rejected') throw p.reason;
  currentProfile = p.value;
  currentRecommendations = r.status === 'fulfilled' ? r.value : null;
  renderProfile();
  renderChat();
  if (r.status === 'rejected') throw new Error(`Профиль загружен, но рекомендации недоступны: ${r.reason.message}`);
}
async function connect() {
  if (busy) return;
  const epoch = ++generation;
  chatController?.abort(); chatMessages = []; chatEvent = null; chatBusy = false;
  employeeId = $('employee').value.trim();
  backendBase = $('base').value.trim();
  api = createApi(backendBase, $('token').value.trim());
  currentProfile = null; currentRecommendations = null;
  $('profile').innerHTML = '<div class="empty">Загрузка профиля…</div>';
  $('overview').innerHTML = ''; $('import-result').innerHTML = ''; notice(); renderChat(); setBusy(true);
  try { if (view === 'hr') await loadHr(epoch); else await refresh(epoch); }
  catch(e) { if(epoch === generation) { notice(e.message,true); $('profile').innerHTML = '<div class="empty">Профиль не загружен. Проверьте идентификатор и ключ доступа.</div>'; } }
  finally { if(epoch === generation) setBusy(false); }
  checkHealth();
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
    acknowledged = true;
    delete all[event]; saveAttempts(all);
    await refresh(epoch);
    notice(result.status === 'already_completed' ? 'Участие уже было выполнено. Загружено актуальное состояние; повторного начисления нет.' : 'Выполнение сохранено. Навыки, история и рекомендации обновлены.');
  } catch(e) {
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
  setBusy(true); let saved = false;
  try { await api.goal(employeeId,{role:goal.role,grade:goal.grade}); saved = true; await refresh(generation); notice('Карьерная цель сохранена.'); }
  catch(e) { notice(`${saved ? 'Цель сохранена, обновите экран. ' : ''}${e.message}`,true); }
  finally { setBusy(false); }
}
async function loadHr(epoch = generation) {
  $('overview').innerHTML = '<div class="empty">Загрузка HR-данных…</div>';
  try {
    const data = await api.overview(); if(epoch !== generation) return;
    const open = id => `<button class="secondary" data-open="${esc(id)}">${esc(id)}</button>`;
    $('overview').innerHTML = `<div class="section-heading"><h2>Развитие команды</h2><button class="secondary" id="refresh-hr">Обновить HR</button></div><p>${data.employees_count} сотрудников · На ${esc(data.as_of)}</p><article><h3>Частые дефициты навыков</h3>${table(['Навык','Сотрудников с разрывом','С критическим разрывом'],data.skill_deficits.map(x=>`<tr><td>${esc(x.skill_id)}</td><td>${x.employees_count}</td><td>${x.critical_count}</td></tr>`))}</article><article><h3>Без подходящего следующего шага</h3>${table(['Сотрудник','Имя','Причина'],data.without_next_step.map(x=>`<tr><td>${open(x.employee_id)}</td><td>${esc(x.name)}</td><td>${esc(x.reason)}</td></tr>`))}</article><article><h3>Участие в активностях</h3>${table(['Сотрудник','Имя','Завершено','В процессе','Отказы / пропуски'],data.participation.map(x=>`<tr><td>${open(x.employee_id)}</td><td>${esc(x.name)}</td><td>${x.completed}</td><td>${x.in_progress}</td><td>${x.missed}</td></tr>`))}</article>`;
    $('refresh-hr').onclick = () => switchView('hr');
    $('overview').querySelectorAll('[data-open]').forEach(b => b.onclick = () => openEmployee(b.dataset.open));
  } catch(e) { $('overview').innerHTML = '<div class="empty">HR-данные недоступны.</div>'; throw e; }
}
async function switchView(next) {
  if(busy) return;
  view = next; $('employee-view').hidden = next !== 'employee'; $('hr-view').hidden = next !== 'hr';
  $('employee-tab').classList.toggle('selected',next === 'employee'); $('hr-tab').classList.toggle('selected',next === 'hr'); notice();
  if(!api) { notice('Сначала введите ключ доступа и подключитесь.'); return; }
  setBusy(true);
  try { if(next === 'hr') await loadHr(); else await refresh(generation); }
  catch(e) { notice(e.message,true); }
  finally { setBusy(false); }
}
function openEmployee(id) {
  if(busy) return;
  $('employee').value = id; view = 'employee'; $('employee-view').hidden = false; $('hr-view').hidden = true;
  $('employee-tab').classList.add('selected'); $('hr-tab').classList.remove('selected'); connect();
}
$('import-form').onsubmit = async event => {
  event.preventDefault(); if(busy || !api) return;
  const file = $('import-file').files[0]; if(!file) return;
  setBusy(true); $('import-result').textContent = `Загрузка ${file.name}…`; let saved = false;
  try {
    if(file.size > 2*1024*1024) throw new Error('Файл больше 2 МБ.');
    let body; try { body = JSON.parse(await file.text()); } catch { throw new Error('Некорректный JSON. Выберите файл внутреннего формата из примера.'); }
    const result = await api.importProfiles(body); saved = true;
    $('import-result').innerHTML = `<p>Импортировано профилей: ${result.employees_imported}; записей истории: ${result.history_imported}.</p>${result.employee_ids.map(id=>`<button class="secondary" data-open="${esc(id)}">Открыть ${esc(id)}</button>`).join(' ')}`;
    $('import-result').querySelectorAll('[data-open]').forEach(b => b.onclick = () => openEmployee(b.dataset.open));
    await loadHr(); notice('Импорт сохранён, HR-данные обновлены.'); checkHealth();
  } catch(e) { if(!saved) $('import-result').textContent = e.message; notice(saved ? `Импорт сохранён, но HR не обновился: ${e.message}` : e.message,true); }
  finally { setBusy(false); }
};
function renderChat() {
  $('chat').innerHTML = `<article class="chat"><h2>Карьерный помощник</h2><p>${CHAT_ENABLED ? 'Задайте вопрос о следующем шаге.' : 'AI-чат пока не подключён'}</p>${chatEvent ? `<p>Активность: <strong>${esc(chatEvent)}</strong> <button class="secondary" id="clear-event">Общий вопрос</button></p>` : ''}<div class="chat-log" role="log">${chatMessages.map(m=>`<p><strong>${m.role === 'user' ? 'Вы' : 'Помощник'}</strong>${esc(m.content)}</p>`).join('')}</div><div class="chat-prompts">${['Почему этот шаг?','Что дальше?','Какие есть альтернативы?'].map(q=>`<button class="secondary" data-prompt="${esc(q)}" ${!CHAT_ENABLED || chatBusy ? 'disabled' : ''}>${q}</button>`).join('')}</div><form id="chat-form"><label>Ваш вопрос<input id="chat-input" maxlength="2000" ${!CHAT_ENABLED || chatBusy ? 'disabled' : ''} required placeholder="Вопрос карьерному помощнику"></label><button ${!CHAT_ENABLED || chatBusy || !currentProfile ? 'disabled' : ''}>${chatBusy ? 'Ожидание ответа…' : 'Отправить'}</button></form><p id="chat-error" role="alert"></p></article>`;
  if($('clear-event')) $('clear-event').onclick = () => { chatEvent = null; renderChat(); };
  $('chat-form').onsubmit = e => { e.preventDefault(); sendChat($('chat-input').value.trim()); };
  $('chat').querySelectorAll('[data-prompt]').forEach(b => b.onclick = () => sendChat(b.dataset.prompt));
}
async function sendChat(message) {
  if(!CHAT_ENABLED || chatBusy || !message || !currentProfile) return;
  const epoch = generation, history = chatMessages.slice(-20);
  chatMessages.push({role:'user',content:message}); chatBusy = true; chatController = new AbortController(); renderChat();
  try {
    const response = await api.chat(employeeId,{message,event_id:chatEvent,history},chatController.signal);
    if(epoch !== generation) return;
    if(typeof response.message !== 'string') throw new Error('Некорректный ответ чата.');
    chatMessages.push({role:'assistant',content:response.message});
  } catch(e) { if(epoch === generation) { chatBusy = false; renderChat(); $('chat-error').textContent = e.status === 404 || e.status === 501 ? 'AI-чат пока не подключён' : e.message; return; } }
  finally { if(epoch === generation) chatBusy = false; }
  if(epoch === generation) renderChat();
}
async function checkHealth() {
  const epoch = generation;
  try { const h = await (api || createApi('', '')).health(); if(epoch === generation) { $('health').textContent = h.demo ? 'Демонстрационные данные' : h.dataset_loaded ? 'Сервер подключён' : 'Данные не загружены'; $('demo').hidden = !h.demo; } }
  catch { if(epoch === generation) $('health').textContent = 'Сервер недоступен'; }
}
$('connect').onsubmit = e => { e.preventDefault(); connect(); };
$('demo').onclick = () => { $('employee').value = 'DEMO_001'; $('token').value = 'demo-employee-1'; openEmployee('DEMO_001'); };
$('employee-tab').onclick = () => switchView('employee'); $('hr-tab').onclick = () => switchView('hr');
renderChat(); checkHealth();
