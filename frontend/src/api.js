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
    const detail = await response.text();
    throw new Error(detail || "分析失敗");
  }
  return response.json();
}
