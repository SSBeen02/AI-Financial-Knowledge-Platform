"""외부 정적 파일이나 라이브러리 없이 동작하는 로컬 채팅 점검 화면."""

DEV_CHAT_HTML = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>나의 경세학당 · 개발용 채팅</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f4f6f8; color: #18202a; }
    main { max-width: 980px; margin: 0 auto; padding: 20px; }
    h1 { margin: 0 0 14px; font-size: 22px; }
    .panel { background: #fff; border: 1px solid #dce1e7; border-radius: 12px; padding: 14px; margin-bottom: 12px; }
    .toolbar, .actions, .composer { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    label { font-size: 13px; color: #56616f; }
    input, select, textarea, button { font: inherit; }
    input, select, textarea { border: 1px solid #c9d0d8; border-radius: 8px; padding: 9px; background: #fff; }
    input { min-width: 180px; }
    textarea { flex: 1; min-height: 54px; resize: vertical; }
    button { border: 0; border-radius: 8px; padding: 9px 12px; background: #2457d6; color: white; cursor: pointer; }
    button.secondary { background: #647184; }
    button.danger { background: #bd2c2c; }
    button:disabled { opacity: .45; cursor: not-allowed; }
    #statusLine { margin-top: 10px; padding: 9px; border-radius: 8px; background: #eef3ff; font-size: 14px; }
    #learningGuide { margin-top: 8px; padding: 9px; border-radius: 8px; background: #f5f1e5; color: #5f4a22; font-size: 13px; }
    .progress-track { height: 10px; margin-top: 10px; overflow: hidden; border-radius: 999px; background: #e3e8ef; }
    #progressBar { width: 0; height: 100%; background: #3a7a35; transition: width .2s ease; }
    #progressText { margin-top: 6px; color: #4c5968; font-size: 12px; }
    #keywords { display: flex; flex-wrap: wrap; gap: 8px; }
    #keywords button { background: #e8efff; color: #173f9e; }
    #quickPrompts { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 9px; }
    #quickPrompts button { background: #f0e8ff; color: #59349a; font-size: 12px; }
    #learningChip { display: none; margin-top: 8px; background: #7a4d19; }
    #chat { min-height: 340px; max-height: 58vh; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
    .message { max-width: 82%; border-radius: 12px; padding: 10px 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .user { align-self: flex-end; background: #2457d6; color: white; }
    .assistant { align-self: flex-start; background: #eef1f4; }
    .meta { margin-top: 7px; font-size: 11px; color: #687482; white-space: normal; }
    .sources { margin-top: 5px; font-size: 11px; color: #40506a; white-space: normal; }
    .answer-notice { margin-top: 8px; padding: 8px; border: 1px solid #e0bd66; border-radius: 8px; background: #fff8df; color: #6a4b00; font-size: 12px; white-space: normal; }
    .suggestion { margin-top: 8px; background: #3a7a35; font-size: 12px; }
    #context { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; font-size: 12px; }
    .hint { color: #6b7684; font-size: 12px; }
    .grow { flex: 1; }
  </style>
</head>
<body>
<main>
  <h1>나의 경세학당 · 개발용 채팅</h1>
  <section class="panel">
    <div class="toolbar">
      <label for="userId">X-User-Id</label>
      <input id="userId" value="local-user-1" autocomplete="off">
      <button id="reload" class="secondary">불러오기</button>
      <span class="grow"></span>
      <label for="stage">스테이지</label>
      <select id="stage">
        <option value="stage1">Stage 1</option><option value="stage2">Stage 2</option>
        <option value="stage3">Stage 3</option><option value="stage4">Stage 4</option>
        <option value="stage5">Stage 5</option>
      </select>
      <button id="changeStage" class="secondary">변경</button>
      <button id="passAll" class="secondary">현재 스테이지 전체 통과</button>
      <button id="reset" class="danger">초기화</button>
    </div>
    <div id="statusLine">상태를 불러오는 중…</div>
    <button id="learningChip" type="button"></button>
    <div id="quickPrompts"></div>
    <div id="learningGuide">학습 안내를 불러오는 중…</div>
    <div class="progress-track"><div id="progressBar"></div></div>
    <div id="progressText">진행률을 불러오는 중…</div>
  </section>

  <section class="panel">
    <div id="keywords"></div>
    <div class="actions" style="margin-top:8px">
      <button id="nextConcepts" class="secondary">다음 5개 보기</button>
      <span id="conceptHint" class="hint"></span>
    </div>
  </section>

  <section class="panel">
    <div id="chat" aria-live="polite"></div>
  </section>

  <section class="panel">
    <div class="composer">
      <textarea id="message" placeholder="경제 개념을 질문해 보세요."></textarea>
      <button id="send">보내기</button>
    </div>
    <div class="actions" style="margin-top:10px">
      <button id="complete" class="secondary">학습 완료</button>
      <button id="quizPass">퀴즈 통과</button>
      <button id="quizFail" class="danger">퀴즈 실패</button>
      <button id="quizRetry" class="secondary">퀴즈 다시 요청</button>
      <button id="viewContext" class="secondary">학습 맥락 보기</button>
    </div>
  </section>

  <section class="panel">
    <strong>학습 맥락 / 오류</strong>
    <pre id="context">아직 표시할 내용이 없습니다.</pre>
  </section>
</main>
<script>
(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    mode: "normal", selectedConceptId: null, lockedConceptId: null,
    conceptOffset: 0, nextOffset: null,
    activeSessionId: null, quizSessionId: null, streaming: false, completeHint: null,
    completionKeys: {}, retryKeys: {}, quizMeta: null,
  };

  const userId = () => $("userId").value.trim();
  const headers = (json = false) => {
    const result = {"X-User-Id": userId()};
    if (json) result["Content-Type"] = "application/json";
    return result;
  };
  async function api(path, options = {}) {
    const response = await fetch(path, {...options, headers: {...headers(Boolean(options.body)), ...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || `${response.status} ${response.statusText}`);
    return data;
  }
  function show(value) {
    $("context").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }
  function setBusy(busy) {
    state.streaming = busy;
    $("send").disabled = busy;
  }
  function sourceText(sources) {
    return (sources || []).map((source) => `${source.term} · ${source.label} · ${Number(source.score).toFixed(3)}`).join("\n");
  }
  function addMessage(role, content, metadata = null) {
    const item = document.createElement("div");
    item.className = `message ${role}`;
    const body = document.createElement("div");
    body.textContent = content;
    item.appendChild(body);
    if (metadata && role === "assistant") {
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = `is_related=${metadata.is_related} · band=${metadata.band || "-"}`;
      item.appendChild(meta);
      const text = sourceText(metadata.display_sources);
      if (text) {
        const sources = document.createElement("div");
        sources.className = "sources";
        sources.textContent = `화면 출처\n${text}`;
        item.appendChild(sources);
      }
    }
    $("chat").appendChild(item);
    $("chat").scrollTop = $("chat").scrollHeight;
    return {item, body};
  }
  function addNotice(item, notice) {
    if (!notice) return;
    const box = document.createElement("div");
    box.className = "answer-notice";
    box.textContent = notice;
    item.appendChild(box);
  }
  function addSuggestion(item, suggestion) {
    if (!suggestion) return;
    const button = document.createElement("button");
    button.className = "suggestion";
    button.textContent = `${suggestion.term} 학습 시작하기`;
    button.addEventListener("click", () => {
      state.selectedConceptId = suggestion.concept_id;
      $("message").value = `${suggestion.term}에 대해 알려줘`;
      $("message").focus();
    });
    item.appendChild(button);
  }

  async function restoreHistory() {
    const messages = await api("/learning/history?limit=50");
    $("chat").replaceChildren();
    for (const message of messages) addMessage(message.role, message.content, message);
  }
  async function loadContexts() {
    const contexts = await api("/learning/learning-contexts?status=completed");
    const actionable = contexts.find((item) => ["pending", "generation_failed"].includes(item.quiz_status));
    state.quizSessionId = actionable ? actionable.session_id : (contexts[0]?.session_id || null);
  }
  async function refreshState() {
    const chatState = await api("/learning/current");
    state.mode = chatState.mode;
    state.activeSessionId = chatState.active_session?.session_id || null;
    state.lockedConceptId = chatState.locked_concept?.concept_id || null;
    state.completeHint = chatState.complete_hint || null;
    const active = chatState.active_session ? ` · active=${chatState.active_session.term} (attempt ${chatState.active_session.attempt})` : "";
    $("statusLine").textContent = `mode=${chatState.mode}${active}${chatState.notice ? ` · ${chatState.notice}` : ""}`;
    $("learningGuide").textContent = chatState.learning_guide;
    const chip = $("learningChip");
    if (chatState.locked_concept) {
      chip.style.display = "inline-block";
      chip.textContent = `학습 중 · ${chatState.locked_concept.term}`;
    } else {
      chip.style.display = "none";
      chip.textContent = "";
    }
    const quick = $("quickPrompts");
    quick.replaceChildren();
    for (const prompt of chatState.quick_prompts || []) {
      const button = document.createElement("button");
      button.textContent = prompt;
      button.addEventListener("click", () => { $("message").value = prompt; $("message").focus(); });
      quick.appendChild(button);
    }
    $("complete").disabled = false;
    const progress = chatState.progress;
    $("progressBar").style.width = `${progress.percent}%`;
    $("progressText").textContent = `${progress.name_ko} · ${progress.percent}% · 남은 개념 ${progress.remaining_count}개`;
    await loadContexts();
    const quizPending = chatState.mode === "quiz_pending" && Boolean(state.quizSessionId);
    $("quizPass").disabled = !quizPending;
    $("quizFail").disabled = !quizPending;
    $("quizRetry").disabled = chatState.mode !== "quiz_generation_failed" || !state.quizSessionId;
    $("viewContext").disabled = !state.quizSessionId;
  }
  async function loadConcepts(offset = 0) {
    const result = await api(`/learning/concepts?offset=${offset}&limit=5`);
    state.conceptOffset = offset;
    state.nextOffset = result.next_offset;
    $("stage").value = result.stage.id;
    const box = $("keywords");
    box.replaceChildren();
    for (const concept of result.concepts) {
      const button = document.createElement("button");
      button.textContent = concept.term;
      button.disabled = state.mode !== "normal" || Boolean(state.lockedConceptId);
      button.addEventListener("click", () => {
        $("message").value = `${concept.term}에 대해 알려줘`;
        state.selectedConceptId = concept.concept_id;
        $("message").focus();
      });
      box.appendChild(button);
    }
    $("nextConcepts").disabled = !result.has_more || state.mode !== "normal" || Boolean(state.lockedConceptId);
    $("conceptHint").textContent = result.concepts.length ? `${offset + 1}번째부터 표시` : "표시할 미학습 개념이 없습니다.";
  }
  async function refreshAll({history = false} = {}) {
    if (!userId()) throw new Error("X-User-Id를 입력하세요.");
    localStorage.setItem("chatDevUserId", userId());
    await refreshState();
    await loadConcepts(0);
    if (history) await restoreHistory();
  }

  function parseEvent(block) {
    let event = "message";
    const data = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return null;
    return {event, data: JSON.parse(data.join("\n"))};
  }
  async function sendMessage() {
    const message = $("message").value.trim();
    if (!message || state.streaming) return;
    const body = {message};
    if (state.selectedConceptId) body.concept_id = state.selectedConceptId;
    if (!body.concept_id && state.mode === "relearn") body.concept_id = state.lockedConceptId;
    state.selectedConceptId = null;
    $("message").value = "";
    addMessage("user", message);
    const assistant = addMessage("assistant", "");
    setBusy(true);
    try {
      const response = await fetch("/learning/messages/stream", {
        method: "POST", headers: headers(true), body: JSON.stringify(body),
      });
      if (!response.ok || !response.body) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.message || `stream failed: ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let doneMetadata = null;
      while (true) {
        const chunk = await reader.read();
        buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done}).replaceAll("\r\n", "\n");
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const parsed = parseEvent(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          if (!parsed) continue;
          if (parsed.event === "token") assistant.body.textContent += parsed.data.delta;
          if (parsed.event === "error") throw new Error(parsed.data.message || "스트림 오류");
          if (parsed.event === "done") doneMetadata = parsed.data;
        }
        $("chat").scrollTop = $("chat").scrollHeight;
        if (chunk.done) break;
      }
      if (!doneMetadata) throw new Error("done 이벤트 없이 스트림이 종료되었습니다.");
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = `is_related=${doneMetadata.is_related} · band=${doneMetadata.band}`;
      assistant.item.appendChild(meta);
      const text = sourceText(doneMetadata.display_sources);
      if (text) {
        const sources = document.createElement("div");
        sources.className = "sources";
        sources.textContent = `화면 출처\n${text}`;
        assistant.item.appendChild(sources);
      }
      addNotice(assistant.item, doneMetadata.notice);
      addSuggestion(assistant.item, doneMetadata.suggested_concept);
      await refreshState();
      await loadConcepts(0);
    } catch (error) {
      assistant.body.textContent = `오류: ${error.message}`;
      show(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function completeLearning() {
    if (!state.activeSessionId) {
      show(state.completeHint || "아직 배우고 있는 개념이 없습니다.");
      return;
    }
    const key = state.completionKeys[state.activeSessionId] || crypto.randomUUID();
    state.completionKeys[state.activeSessionId] = key;
    const context = await api(`/learning/sessions/${state.activeSessionId}/complete`, {
      method: "POST", headers: {"Idempotency-Key": key},
    });
    state.quizSessionId = context.session_id;
    state.quizMeta = {concept_id: context.concept.concept_id, stage_id: context.concept.stage};
    show(context);
    await refreshState();
    await loadConcepts(0);
  }
  async function reportQuiz(passed) {
    if (!state.quizSessionId) return;
    if (!state.quizMeta) {
      const context = await api(`/learning/sessions/${state.quizSessionId}/learning-context`);
      state.quizMeta = {concept_id: context.concept.concept_id, stage_id: context.concept.stage};
    }
    const result = await api(`/learning/sessions/${state.quizSessionId}/quiz-result`, {
      method: "POST", body: JSON.stringify({
        submission_id: crypto.randomUUID(),
        concept_id: state.quizMeta.concept_id,
        stage_id: state.quizMeta.stage_id,
        correct_count: passed ? 2 : 1,
        passed,
      }),
    });
    show(result);
    await refreshState();
    await loadConcepts(0);
  }
  async function retryQuiz() {
    if (!state.quizSessionId) return;
    const key = state.retryKeys[state.quizSessionId] || crypto.randomUUID();
    state.retryKeys[state.quizSessionId] = key;
    const result = await api(`/learning/sessions/${state.quizSessionId}/quiz-retry`, {
      method: "POST", headers: {"Idempotency-Key": key},
    });
    state.quizSessionId = result.session_id;
    state.quizMeta = {concept_id: result.concept_id, stage_id: result.stage_id};
    show(result);
    await refreshState();
  }

  $("message").addEventListener("input", () => { state.selectedConceptId = null; });
  $("message").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); }
  });
  $("send").addEventListener("click", sendMessage);
  $("reload").addEventListener("click", () => refreshAll({history: true}).catch((e) => show(e.message)));
  $("nextConcepts").addEventListener("click", () => {
    if (state.nextOffset !== null) loadConcepts(state.nextOffset).catch((e) => show(e.message));
  });
  $("changeStage").addEventListener("click", async () => {
    try {
      await api("/learning/dev/stage", {method: "POST", body: JSON.stringify({stage: $("stage").value})});
      state.selectedConceptId = null;
      await refreshAll();
    } catch (e) { show(e.message); }
  });
  $("passAll").addEventListener("click", async () => {
    if (!confirm("현재 스테이지의 모든 개념을 통과 처리할까요?")) return;
    try {
      const result = await api("/learning/dev/pass-all", {method: "POST"});
      state.selectedConceptId = null;
      show(`전체 통과 처리했습니다. 현재 스테이지: ${result.stage}`);
      await refreshAll();
    } catch (e) { show(e.message); }
  });
  $("reset").addEventListener("click", async () => {
    if (!confirm(`${userId()} 사용자의 채팅·학습 상태를 초기화할까요?`)) return;
    try {
      await api("/learning/dev/reset", {method: "POST"});
      state.selectedConceptId = null;
      $("chat").replaceChildren();
      show("초기화했습니다.");
      await refreshAll();
    } catch (e) { show(e.message); }
  });
  $("complete").addEventListener("click", () => completeLearning().catch((e) => show(e.message)));
  $("quizPass").addEventListener("click", () => reportQuiz(true).catch((e) => show(e.message)));
  $("quizFail").addEventListener("click", () => reportQuiz(false).catch((e) => show(e.message)));
  $("quizRetry").addEventListener("click", () => retryQuiz().catch((e) => show(e.message)));
  $("learningChip").addEventListener("click", () => {
    const first = $("quickPrompts").querySelector("button");
    if (first) { $("message").value = first.textContent; $("message").focus(); }
  });
  $("viewContext").addEventListener("click", async () => {
    try { show(await api(`/learning/sessions/${state.quizSessionId}/learning-context`)); }
    catch (e) { show(e.message); }
  });

  const saved = localStorage.getItem("chatDevUserId");
  if (saved) $("userId").value = saved;
  refreshAll({history: true}).catch((error) => show(error.message));
})();
</script>
</body>
</html>
"""
