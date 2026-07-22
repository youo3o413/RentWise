import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  Building2,
  Check,
  ChevronDown,
  ChevronUp,
  CircleDollarSign,
  Clock3,
  Home,
  LoaderCircle,
  MapPin,
  Route,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { getHealth, getRecommendation } from "./api";

const initialForm = {
  budget: 15000,
  destination: "政治大學",
  max_commute_minutes: 25,
  needs_window: true,
  noise_preference: "quiet",
  needs_elevator: false,
  needs_convenience_store: true,
  max_floor_without_elevator: 3,
  preferences: ["採光良好", "可開伙"],
};

const agentMeta = {
  "Data Loader": { icon: Building2, label: "房源資料載入" },
  "Location Agent": { icon: MapPin, label: "地點與通勤分析" },
  "Cost Agent": { icon: CircleDollarSign, label: "真實生活成本估算" },
  "Property Agent": { icon: Home, label: "房況與設備檢查" },
  "Suitability Agent": { icon: ShieldCheck, label: "個人適配度評估" },
  "Comparison Agent": { icon: Bot, label: "跨房源比較決策" },
};

function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      className={`toggle ${checked ? "active" : ""}`}
      onClick={() => onChange(!checked)}
      aria-pressed={checked}
    >
      <span className="toggle-dot" />
      {label}
    </button>
  );
}

function AgentPipeline({ trace, loading }) {
  const defaultAgents = Object.keys(agentMeta);
  const completed = new Map((trace || []).map((item) => [item.agent, item]));

  return (
    <section className="panel pipeline-panel">
      <div className="section-title">
        <div>
          <span className="eyebrow">LANGGRAPH WORKFLOW</span>
          <h2>Agent 協作流程</h2>
        </div>
        {loading && <LoaderCircle className="spin" size={22} />}
      </div>
      <div className="pipeline">
        {defaultAgents.map((name, index) => {
          const meta = agentMeta[name];
          const Icon = meta.icon;
          const done = completed.has(name);
          return (
            <div className="pipeline-row" key={name}>
              <div className={`agent-icon ${done ? "done" : loading ? "pending" : ""}`}>
                {done ? <Check size={18} /> : <Icon size={18} />}
              </div>
              <div className="agent-copy">
                <strong>{name}</strong>
                <span>{completed.get(name)?.message || meta.label}</span>
              </div>
              <span className={`status-pill ${done ? "done" : ""}`}>
                {done ? "完成" : loading && index === completed.size ? "執行中" : "待命"}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ScoreRing({ score }) {
  const rounded = Math.round(score);
  return (
    <div className="score-ring" style={{ "--score": `${rounded * 3.6}deg` }}>
      <div>
        <strong>{rounded}</strong>
        <span>適配分</span>
      </div>
    </div>
  );
}

function ResultCard({ item }) {
  const [open, setOpen] = useState(item.rank === 1);
  const p = item.property;
  return (
    <article className={`result-card ${item.rank === 1 ? "winner" : ""}`}>
      <div className="rank-badge">#{item.rank}</div>
      <img src={p.image_url} alt={p.title} />
      <div className="result-main">
        <div className="result-heading">
          <div>
            <div className="title-line">
              <h3>{p.title}</h3>
              {item.rank === 1 && <span className="best-tag"><Sparkles size={14} />首選</span>}
            </div>
            <p><MapPin size={15} />{p.address}</p>
          </div>
          <ScoreRing score={item.total_score} />
        </div>

        <div className="metrics-grid">
          <div><span>預估月支出</span><strong>NT$ {item.estimated_monthly_cost.toLocaleString()}</strong></div>
          <div><span>通勤時間</span><strong>{p.commute_minutes} 分鐘</strong></div>
          <div><span>窗戶</span><strong>{p.window_type}</strong></div>
          <div><span>樓層</span><strong>{p.floor}F／{p.has_elevator ? "有電梯" : "無電梯"}</strong></div>
        </div>

        <p className="recommendation">{item.recommendation}</p>

        <div className="pros-cons">
          <div>
            <h4><Check size={16} />主要優勢</h4>
            <ul>{item.strengths.slice(0, 3).map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
          <div>
            <h4><TriangleAlert size={16} />需要取捨</h4>
            <ul>{item.tradeoffs.slice(0, 3).map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
        </div>

        <button className="detail-button" onClick={() => setOpen(!open)}>
          查看各 Agent 分析 {open ? <ChevronUp size={17} /> : <ChevronDown size={17} />}
        </button>

        {open && (
          <div className="assessment-list">
            {Object.values(item.assessments).map((assessment) => (
              <div className="assessment" key={assessment.agent}>
                <div>
                  <strong>{assessment.agent}</strong>
                  <span>{assessment.summary}</span>
                </div>
                <b>{Math.round(assessment.score)}</b>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

export default function App() {
  const [form, setForm] = useState(initialForm);
  const [preferenceText, setPreferenceText] = useState(initialForm.preferences.join("、"));
  const [data, setData] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  const modeLabel = useMemo(() => {
    if (data?.mode === "ai") return "OpenAI AI mode";
    if (health?.openai_enabled) return "OpenAI ready";
    return "Demo rules mode";
  }, [data, health]);

  function update(name, value) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setData(null);
    try {
      const payload = {
        ...form,
        budget: Number(form.budget),
        max_commute_minutes: Number(form.max_commute_minutes),
        max_floor_without_elevator: Number(form.max_floor_without_elevator),
        preferences: preferenceText.split(/[、,，]/).map((x) => x.trim()).filter(Boolean),
      };
      const result = await getRecommendation(payload);
      setData(result);
    } catch (err) {
      setError("分析失敗：請確認 FastAPI 已在 8000 port 啟動。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <header className="hero">
        <nav>
          <div className="brand"><div><Home size={21} /></div><strong>RentWise</strong></div>
          <span className="mode-badge"><span />{modeLabel}</span>
        </nav>
        <div className="hero-copy">
          <span className="eyebrow">MULTI-AGENT RENTAL DECISION PLATFORM</span>
          <h1>不是幫你找房，<br />而是幫你做出<span>更好的租屋決策。</span></h1>
          <p>多個 AI Agent 分別分析地點、成本、房況與生活偏好，再共同完成跨房源比較。</p>
        </div>
      </header>

      <div className="app-shell">
        <form className="panel form-panel" onSubmit={submit}>
          <div className="section-title">
            <div>
              <span className="eyebrow">YOUR REQUIREMENTS</span>
              <h2>設定租屋需求</h2>
            </div>
            <Route size={24} />
          </div>

          <div className="form-grid">
            <Field label="每月總預算" hint="包含管理費與預估水電">
              <div className="input-prefix"><span>NT$</span><input type="number" value={form.budget} onChange={(e) => update("budget", e.target.value)} /></div>
            </Field>
            <Field label="通勤目的地">
              <input value={form.destination} onChange={(e) => update("destination", e.target.value)} />
            </Field>
            <Field label="最長通勤時間">
              <div className="input-suffix"><input type="number" value={form.max_commute_minutes} onChange={(e) => update("max_commute_minutes", e.target.value)} /><span>分鐘</span></div>
            </Field>
            <Field label="噪音偏好">
              <select value={form.noise_preference} onChange={(e) => update("noise_preference", e.target.value)}>
                <option value="quiet">希望安靜</option>
                <option value="balanced">可以接受一般噪音</option>
                <option value="no_preference">沒有偏好</option>
              </select>
            </Field>
          </div>

          <div className="toggle-grid">
            <Toggle checked={form.needs_window} onChange={(v) => update("needs_window", v)} label="需要對外窗" />
            <Toggle checked={form.needs_elevator} onChange={(v) => update("needs_elevator", v)} label="一定要有電梯" />
            <Toggle checked={form.needs_convenience_store} onChange={(v) => update("needs_convenience_store", v)} label="附近需有便利商店" />
          </div>

          <div className="form-grid">
            <Field label="無電梯可接受最高樓層">
              <div className="input-suffix"><input type="number" value={form.max_floor_without_elevator} onChange={(e) => update("max_floor_without_elevator", e.target.value)} /><span>樓</span></div>
            </Field>
            <Field label="其他偏好" hint="使用頓號或逗號分隔">
              <input value={preferenceText} onChange={(e) => setPreferenceText(e.target.value)} placeholder="採光良好、可開伙" />
            </Field>
          </div>

          <button className="submit-button" disabled={loading}>
            {loading ? <><LoaderCircle className="spin" size={20} />Agents 分析中...</> : <><Sparkles size={20} />啟動 Multi-Agent 分析</>}
          </button>
          {error && <p className="error">{error}</p>}
        </form>

        <AgentPipeline trace={data?.trace} loading={loading} />

        {data && (
          <section className="results-section">
            <div className="decision-summary">
              <div className="summary-icon"><Bot size={26} /></div>
              <div>
                <span className="eyebrow">COMPARISON AGENT DECISION</span>
                <h2>最終決策摘要</h2>
                <p>{data.summary}</p>
              </div>
            </div>
            <div className="results-heading">
              <div>
                <span className="eyebrow">RANKED RESULTS</span>
                <h2>房源推薦排名</h2>
              </div>
              <span>{data.results.length} 筆房源完成分析</span>
            </div>
            <div className="results-list">
              {data.results.map((item) => <ResultCard item={item} key={item.property.id} />)}
            </div>
          </section>
        )}

        {!data && !loading && (
          <section className="empty-state">
            <Clock3 size={30} />
            <h3>Agent 團隊正在待命</h3>
            <p>設定需求後啟動分析，系統會同步展示每個 Agent 的分工與最終排名。</p>
          </section>
        )}
      </div>
      <footer>RentWise · Agentic AI Competition Demo · LangGraph × FastAPI × React</footer>
    </main>
  );
}
