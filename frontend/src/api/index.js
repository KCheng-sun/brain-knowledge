import axios from "axios";

const client = axios.create({ baseURL: "/api" });

export async function addNote(text, title) {
  const { data } = await client.post("/notes", { text, title: title || undefined });
  return data;
}

export async function uploadFiles(formData) {
  const { data } = await client.post("/ingest", formData);
  return data;
}

export async function searchNotes(query, tag, topK = 5) {
  const { data } = await client.get("/search", {
    params: { query, tag: tag || undefined, top_k: topK },
  });
  return data;
}

export async function askQuestion(question) {
  const { data } = await client.post("/ask", { question });
  return data;
}

export async function getStatus() {
  const { data } = await client.get("/status");
  return data;
}

export async function getConnections() {
  const { data } = await client.get("/connections");
  return data;
}

export async function getDigest(weekly = false) {
  const { data } = await client.get("/digest", { params: { weekly } });
  return data;
}

export async function getReview(limit = 5) {
  const { data } = await client.get("/review", { params: { limit } });
  return data;
}

// ============ 会话管理 ============

export async function createSession(title) {
  const { data } = await client.post("/sessions", { title });
  return data;
}

export async function listSessions() {
  const { data } = await client.get("/sessions");
  return data;
}

export async function getSessionMessages(sessionId) {
  const { data } = await client.get(`/sessions/${sessionId}/messages`);
  return data;
}

export async function deleteSession(sessionId) {
  const { data } = await client.delete(`/sessions/${sessionId}`);
  return data;
}

export async function listFragments() {
  const { data } = await client.get("/fragments");
  return data;
}

// ============ 可观测性（Phase 5A） ============

export async function getHealth() {
  const { data } = await client.get("/health");
  return data;
}

export async function getMetricsSummary(hours = 24) {
  const { data } = await client.get("/metrics/summary", { params: { hours } });
  return data;
}

export async function getRecentTraces(limit = 20) {
  const { data } = await client.get("/metrics/traces", { params: { limit } });
  return data;
}

export async function getTraceDetail(traceId) {
  const { data } = await client.get(`/metrics/traces/${traceId}`);
  return data;
}

// ============ 成本治理（Phase 5B） ============

export async function getCostSummary() {
  const { data } = await client.get("/cost/summary");
  return data;
}

export async function getCostByModel(hours = 24) {
  const { data } = await client.get("/cost/by-model", { params: { hours } });
  return data;
}

export async function getCostByDay(days = 30) {
  const { data } = await client.get("/cost/by-day", { params: { days } });
  return data;
}

// ============ 评估反馈（Phase 5D FR54） ============

export async function submitEvalFeedback(traceId, question, answer, reason = "user_thumbs_down") {
  const { data } = await client.post("/eval/feedback", {
    trace_id: traceId,
    question,
    answer,
    reason,
  });
  return data;
}

// ============ 评估分数（Phase 5D FR55） ============

export async function getEvalScores(limit = 50) {
  const { data } = await client.get("/eval/scores", { params: { limit } });
  return data;
}

export async function getEvalScoreSummary() {
  const { data } = await client.get("/eval/scores/summary");
  return data;
}

export async function runEvalDataset(limit = 0) {
  const { data } = await client.post("/eval/run", null, { params: { limit } });
  return data;
}

export async function runJudgeSample(sampleRate = 0.1, limit = 10) {
  const { data } = await client.post("/eval/judge", null, { params: { sample_rate: sampleRate, limit } });
  return data;
}

export async function getBadCases() {
  const { data } = await client.get("/eval/bad-cases");
  return data;
}

export async function deleteBadCase(caseId) {
  const { data } = await client.delete(`/eval/bad-cases/${caseId}`);
  return data;
}

export async function badCaseToGolden(caseId, minScore = 0.7) {
  const { data } = await client.post(`/eval/bad-cases/${caseId}/to-golden`, null, {
    params: { min_score: minScore },
  });
  return data;
}

export async function getGoldenCases(enabledOnly = false) {
  const { data } = await client.get("/eval/golden-cases", {
    params: { enabled_only: enabledOnly },
  });
  return data;
}

export async function saveGoldenCase(caseData) {
  const { data } = await client.post("/eval/golden-cases", caseData);
  return data;
}

export async function deleteGoldenCase(caseId) {
  const { data } = await client.delete(`/eval/golden-cases/${caseId}`);
  return data;
}

export async function toggleGoldenCase(caseId) {
  const { data } = await client.post(`/eval/golden-cases/${caseId}/toggle`);
  return data;
}

export async function seedGoldenCases() {
  const { data } = await client.post("/eval/seed");
  return data;
}

export async function getEvalRuns(limit = 20, runType = null) {
  const { data } = await client.get("/eval/runs", {
    params: { limit, run_type: runType || undefined },
  });
  return data;
}

// ---- Prompts（Phase 5E） ----

export async function listPrompts() {
  const { data } = await client.get("/prompts");
  return data;
}

export async function getPrompt(promptKey) {
  const { data } = await client.get(`/prompts/${promptKey}`);
  return data;
}

export async function updatePrompt(promptKey, content, enabled = null) {
  const { data } = await client.put(`/prompts/${promptKey}`, {
    content,
    enabled,
  });
  return data;
}

export async function listPromptVersions(promptKey) {
  const { data } = await client.get(`/prompts/${promptKey}/versions`);
  return data;
}

export async function getPromptVersion(promptKey, version) {
  const { data } = await client.get(`/prompts/${promptKey}/versions/${version}`);
  return data;
}

export async function restorePromptVersion(promptKey, version) {
  const { data } = await client.post(
    `/prompts/${promptKey}/versions/${version}/restore`
  );
  return data;
}
