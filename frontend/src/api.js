const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function getHealth() {
  const response = await fetch(`${API_BASE}/api/health`);
  if (!response.ok) throw new Error("無法連線至後端");
  return response.json();
}

export async function getRecommendation(requirements) {
  const response = await fetch(`${API_BASE}/api/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requirements),
  });
  if (!response.ok) {
    let detail = "分析失敗";
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = await response.text() || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function parseRequirements(text, current) {
  const response = await fetch(`${API_BASE}/api/parse-requirements`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, current }),
  });
  if (!response.ok) {
    let detail = "Requirement Agent 無法解析需求";
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = (await response.text()) || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function resolveDestination(query, signal) {
  const response = await fetch(`${API_BASE}/api/resolve-destination`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });
  if (!response.ok) {
    let detail = "無法辨識這個目的地";
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = (await response.text()) || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function getMapContext(payload) {
  const response = await fetch(`${API_BASE}/api/map-context`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let detail = "無法載入地圖資料";
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = (await response.text()) || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}
