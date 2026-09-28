const assistantState = { skills: [], messages: [] };

function assistantLayout() {
  const root = $('#assistant-root');
  root.classList.remove('coming-soon');
  root.innerHTML = `<div class="assistant-grid"><div class="assistant-sources">
    <div class="panel-heading"><div><p class="eyebrow">REFERENCES</p><h2>策略资料</h2></div><span class="muted">只读取文本</span></div>
    <label class="upload-tile">选择本地 skill 文件夹<input id="skill-folder" type="file" webkitdirectory multiple hidden><small>读取 SKILL.md 与 Markdown / TXT 附件；不执行脚本</small></label>
    <label class="field-label">公开 GitHub 仓库地址<input id="github-url" type="url" placeholder="https://github.com/owner/repo"></label>
    <button id="github-import" class="secondary-button">从 GitHub 导入 ↘</button>
    <p class="inline-message" id="skill-message"></p>
    <div class="result-section-title">已导入资料 <span>最多选择五项</span></div><div id="skill-list" class="skill-list"></div>
  </div><div class="assistant-chat"><div class="panel-heading"><div><p class="eyebrow">LOCAL DSH</p><h2>策略问答</h2></div><span class="chip" id="dsh-status">检查连接中</span></div>
    <p class="assistant-note">可询问策略逻辑、指标含义与参数建议。回答仅供研究参考，实际表现请到策略回测验证。</p>
    <div id="chat-messages" class="chat-messages"><div class="empty-chart"><strong>从一个问题开始</strong><span>例如：海龟突破在日线回测中，窗口参数怎么选？</span></div></div>
    <label class="field-label">你的问题<textarea id="chat-question" maxlength="4000" rows="4" placeholder="描述你想理解的策略或参数…"></textarea></label>
    <div class="assistant-actions"><button id="chat-send" class="primary-button">发送给本机 DSH ↗</button><span id="chat-message" class="inline-message"></span></div>
  </div></div>`;
  $('#skill-folder').addEventListener('change', importLocalFolder);
  $('#github-import').addEventListener('click', importGithubSkill);
  $('#chat-send').addEventListener('click', sendAssistantQuestion);
}

async function loadSkills() {
  try {
    assistantState.skills = (await api('/api/skills')).items;
    const box = $('#skill-list');
    box.innerHTML = assistantState.skills.length ? assistantState.skills.map((item) => `<label class="skill-item"><input type="checkbox" value="${escapeHtml(item.id)}"><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.description || item.source)}</small></span></label>`).join('') : '<div class="empty-message">尚未导入 SKILL.md。</div>';
  } catch (error) { $('#skill-message').textContent = error.message; }
}

async function importLocalFolder(event) {
  const input = event.target;
  const message = $('#skill-message');
  try {
    const picked = [...input.files];
    const textFiles = picked.filter((file) => /\.(md|txt)$/i.test(file.name));
    if (!textFiles.length || textFiles.length > 128 || textFiles.some((file) => file.size > 256000) || textFiles.reduce((sum, file) => sum + file.size, 0) > 1000000) {
      throw new Error('请选择含 SKILL.md 的目录，文本文件最多 128 个、总计不超过 1 MB。');
    }
    message.textContent = '正在读取所选目录…';
    const files = await Promise.all(textFiles.map(async (file) => ({ path: file.webkitRelativePath || file.name, content: await file.text() })));
    const result = await api('/api/skills/local', { method: 'POST', body: JSON.stringify({ files, source: '本地目录' }) });
    message.textContent = `已导入 ${result.items.length} 个 skill。`;
    await loadSkills();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { input.value = ''; }
}

async function importGithubSkill() {
  const button = $('#github-import'), message = $('#skill-message');
  try {
    const url = $('#github-url').value.trim();
    if (!url) throw new Error('请输入公开 GitHub 仓库地址。');
    button.disabled = true; message.textContent = '正在从 GitHub 读取文本…';
    const result = await api('/api/skills/github', { method: 'POST', body: JSON.stringify({ url }) });
    message.textContent = `已从 GitHub 导入 ${result.items.length} 个 skill。`;
    await loadSkills();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { button.disabled = false; }
}

async function refreshDshStatus() {
  try {
    const status = await api('/api/assistant/status');
    const chip = $('#dsh-status');
    chip.textContent = status.connected ? `已连接 · ${status.model || 'DSH'}` : '连接不可用';
    chip.classList.toggle('warn', !status.connected);
    chip.title = status.error || '';
    $('#chat-send').disabled = !status.connected;
    if (!status.connected) $('#chat-message').textContent = status.error;
  } catch (error) { $('#dsh-status').textContent = '连接不可用'; $('#chat-message').textContent = error.message; }
}

function renderAssistantMessages() {
  $('#chat-messages').innerHTML = assistantState.messages.map((item) => `<div class="chat-bubble ${item.role}"><small>${item.role === 'user' ? '你' : 'DSH 策略助手'}</small><p>${escapeHtml(item.text).replace(/\n/g, '<br>')}</p></div>`).join('');
  $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
}

async function sendAssistantQuestion() {
  const question = $('#chat-question').value.trim();
  const message = $('#chat-message'), button = $('#chat-send');
  if (!question) { message.textContent = '请先输入问题。'; return; }
  const skill_ids = [...document.querySelectorAll('#skill-list input:checked')].map((item) => item.value);
  if (skill_ids.length > 5) { message.textContent = '一次最多选择五项资料。'; return; }
  try {
    button.disabled = true; button.textContent = 'DSH 正在回答…'; message.textContent = '';
    assistantState.messages.push({ role: 'user', text: question }); renderAssistantMessages();
    const result = await api('/api/assistant/chat', { method: 'POST', body: JSON.stringify({ question, skill_ids }) });
    assistantState.messages.push({ role: 'assistant', text: result.answer }); renderAssistantMessages();
    $('#chat-question').value = '';
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { button.textContent = '发送给本机 DSH ↗'; button.disabled = false; }
}

assistantLayout();
loadSkills();
refreshDshStatus();
