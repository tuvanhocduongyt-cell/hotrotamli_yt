/* Shared helpers use textContent for all AI/student content. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  async function post(url, payload) {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Learning-CSRF': document.body.dataset.csrf}, body: JSON.stringify(payload)});
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('Máy chủ chưa phản hồi hợp lệ. Hãy thử lại.'); }
    if (!response.ok) { const error = new Error(data.error || 'Chưa thực hiện được. Hãy thử lại.'); error.data = data; throw error; }
    return data;
  }
  function status(node, message, error = false) { node.textContent = message; node.className = `status ${error ? 'error' : 'success'}`; }
  function element(tag, text, cls) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; }
  async function busy(button, action) { button.disabled = true; try { return await action(); } finally { button.disabled = false; } }
  const create = $('create-task');
  if (create) create.addEventListener('submit', event => { event.preventDefault(); busy(create.querySelector('button'), async () => {
    status($('create-status'), 'AI đang đọc các trang SGK và tạo nhiệm vụ. Vui lòng chờ…');
    try { const data = await post('/api/learning/tasks', {...Object.fromEntries(new FormData(create)), mode: create.dataset.mode}); window.location.href = data.url; }
    catch (error) { status($('create-status'), error.message, true); }
  }); });
  document.querySelectorAll('.teacher-review').forEach(form => form.addEventListener('submit', event => { event.preventDefault(); busy(form.querySelector('button'), async () => {
    try { await post(`/api/learning/review/${encodeURIComponent(form.dataset.attempt)}`, Object.fromEntries(new FormData(form))); status(form.querySelector('.status'), 'Đã lưu nhận xét.'); }
    catch (error) { status(form.querySelector('.status'), error.message, true); }
  }); }));
  if (!$('work-data')) return;
  const config = JSON.parse($('work-data').textContent), writing = $('writing');
  const endpoint = `/api/learning/task/${encodeURIComponent(config.taskId)}/`;
  let retryId = config.latest && !config.latest.feedback ? config.latest.id : null;
  let retryText = retryId ? config.latest.text : null;
  let working = false;
  function lock(value) { working = value; ['analyze', 'save-draft', 'retry-ai', 'ask-ai'].forEach(id => $(id).disabled = value || config.role !== 'student'); writing.readOnly = value; }
  function check() {
    $('word-count').textContent = `${writing.value.length.toLocaleString('vi-VN')} / 18.000 ký tự`;
    $('retry-ai').hidden = !retryId || writing.value.trim() !== retryText;
    if (!$('structure-checks')) return;
    const text = writing.value.toLocaleLowerCase('vi').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');
    const rules = [['Vai trò', /dong vai|vai tro|nha nghien cuu|su gia|giao vien|chuyen gia/], ['Kiểm chứng', /kiem chung|kiem tra|doi chieu|can cu|nguon|bang chung/], ['Phản biện', /phan bien|phan bac|goc nhin|doi lap|chua chac|sai sot/], ['Kết luận lại', /ket luan|dieu chinh|muc do chac|gioi han/]];
    $('structure-checks').replaceChildren(...rules.map(([label, pattern]) => { const found = pattern.test(text); return element('span', `${found ? '✓' : '○'} ${label}`, found ? 'found' : ''); }));
  }
  function feedback(data, delta) {
    const target = $('feedback'); target.replaceChildren();
    $('score-value').textContent = data.score;
    for (const criterion of data.criteria) {
      const block = element('div', null, 'criterion'), row = element('div');
      row.append(element('strong', criterion.label), element('span', `${criterion.level} · ${criterion.score}/2,5`, `level ${criterion.level === 'Đạt' ? 'met' : criterion.level === 'Chưa rõ' ? 'partial' : 'missing'}`));
      block.append(row, element('p', criterion.comment)); target.append(block);
    }
    for (const [key, title] of [['strengths', 'Điểm em đã làm tốt'], ['improvements', 'Bài của em có thể cải thiện ở đâu?'], ['rewrite_hint', 'Gợi ý viết lại']]) {
      const section = element('div', null, 'feedback-section'); section.append(element('h3', title), element('p', data[key], 'preserve')); target.append(section);
    }
    const revise = element('button', '✎ Thử viết lại', 'button secondary rewrite-button'); revise.type = 'button';
    revise.addEventListener('click', () => { writing.focus(); writing.scrollIntoView({behavior: 'smooth', block: 'center'}); }); target.append(revise);
    if (data.model) target.append(element('p', `Model: ${data.model} · Rubric v1`, 'muted'));
    $('score-delta').textContent = delta == null ? '' : `So với lần được nhận xét trước: ${delta > 0 ? '+' : ''}${delta} điểm. Đọc cùng nhận xét từng tiêu chí.`;
  }
  writing.addEventListener('input', check); check(); lock(false);
  if (config.latest && config.latest.feedback) feedback(config.latest.feedback);
  if (config.role !== 'student') status($('work-status'), 'Chế độ xem của giáo viên. Học sinh đăng nhập để viết và nộp bài.');
  $('save-draft').addEventListener('click', async () => {
    if (working) return; lock(true);
    try { await post(endpoint + 'draft', {text: writing.value}); status($('work-status'), 'Đã lưu bản nháp.'); }
    catch (error) { status($('work-status'), error.message, true); } finally { lock(false); }
  });
  async function analyze(retry = false) {
    if (working) return; lock(true); status($('work-status'), 'Đang lưu bài và phân tích theo 4 tiêu chí…');
    try {
      const data = await post(endpoint + 'analyze', {text: writing.value, ...(retry ? {retry_id: retryId} : {})});
      feedback(data.feedback, data.delta); retryId = null; retryText = null; check();
      status($('work-status'), 'Đã lưu bài và nhận xét trong hồ sơ. Em hãy đọc góp ý và thử viết lại.');
    } catch (error) {
      if (error.data && error.data.pending) { retryId = error.data.attempt_id; retryText = writing.value.trim(); check(); }
      status($('work-status'), error.message, true);
    } finally { lock(false); }
  }
  $('analyze').addEventListener('click', () => analyze(Boolean(retryId && writing.value.trim() === retryText)));
  $('retry-ai').addEventListener('click', () => analyze(true));
  $('ask-ai').addEventListener('click', async () => {
    if (working) return; lock(true); $('ai-reply').textContent = 'AI đang đối chiếu trang sách…';
    try { const data = await post(endpoint + 'ask', {text: writing.value, question: $('ai-question').value}); $('ai-reply').textContent = data.reply; }
    catch (error) { $('ai-reply').textContent = error.message; } finally { lock(false); }
  });
})();
