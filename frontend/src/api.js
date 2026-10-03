const API_BASE = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

function formatErrorDetail(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return "";
        const field = Array.isArray(item.loc)
          ? item.loc.filter((part) => !["body", "query", "path"].includes(part)).join(".")
          : "";
        const message = item.msg || item.message || item.error || "";
        if (!message) return "";
        return field ? `${field}：${message}` : message;
      })
      .filter(Boolean);
    if (messages.length) return messages.join("；");
  }

  if (detail && typeof detail === "object") {
    const message = detail.message || detail.msg || detail.error;
    if (typeof message === "string" && message.trim()) return message;
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }

  return fallback;
}

async function responseError(response, fallback) {
  const raw = await response.text();
  if (!raw) return fallback;
  try {
    const body = JSON.parse(raw);
    return formatErrorDetail(body?.detail ?? body, fallback);
  } catch {
    return raw;
  }
}

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
    throw new Error(await responseError(response, "分析失敗"));
  }
  return response.json();
}

export async function sendRecommendationFeedback(threadId, feedback) {
  const response = await fetch(
    `${API_BASE}/api/recommend/${encodeURIComponent(threadId)}/feedback`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(feedback),
    },
  );
  if (!response.ok) {
    throw new Error(await responseError(response, "無法更新推薦偏好"));
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
    throw new Error(
      await responseError(response, "Requirement Agent 無法解析需求"),
    );
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
    throw new Error(await responseError(response, "無法辨識這個目的地"));
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
    throw new Error(await responseError(response, "無法載入地圖資料"));
  }
  return response.json();
}
