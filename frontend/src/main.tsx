import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileCheck2,
  FileText,
  FolderOpen,
  GraduationCap,
  HelpCircle,
  LayoutDashboard,
  ListChecks,
  Loader2,
  LogOut,
  Menu,
  MoreHorizontal,
  Plus,
  Presentation,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
  Eye,
  EyeOff,
  Zap,
  Trash2,
  Undo2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  api,
  dateTime,
  fileName,
  friendlyError,
  outputNames,
  providerNames,
  sizeText,
  statusNames,
} from "./api";
import type { Job, Material, Output, Overview, Settings } from "./api";
import "./style.css";
import { TemplateLibrary, TemplateSelect } from "./templates";
import type { WordTemplate } from "./templates";
import { PptSelect, PptTemplateLibrary, PptViewer } from "./ppt";
import type { PptTemplate } from "./ppt";

const AppContext = createContext<{
  overview: Overview | null;
  refresh: () => void;
  notify: (text: string, error?: boolean) => void;
}>({ overview: null, refresh: () => {}, notify: () => {} });
function useLoad<T>(path: string, interval = 0) {
  const [data, setData] = useState<T | null>(null);
  const [dataPath, setDataPath] = useState(path);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  useEffect(() => {
    const changed = () => reload();
    window.addEventListener("jobs-changed", changed);
    let active = true,
      busy = false;
    const read = async () => {
      if (busy) return;
      busy = true;
      try {
        const result = await api<T>(path);
        if (active) {
          setDataPath(path);
          setData(result);
          setError("");
        }
      } catch (e) {
        if (active) {
          setDataPath(path);
          setData(null);
          setError((e as Error).message);
        }
      } finally {
        busy = false;
        if (active) setLoading(false);
      }
    };
    setLoading(true);
    void read();
    const timer = interval ? window.setInterval(read, interval) : undefined;
    return () => {
      window.removeEventListener("jobs-changed", changed);
      active = false;
      window.clearInterval(timer);
    };
  }, [path, interval, version]);
  return {
    data: dataPath === path ? data : null,
    error: dataPath === path ? error : "",
    loading: dataPath !== path || loading,
    reload,
  };
}
const navItems: [string, string, LucideIcon][] = [
  ["", "工作台", LayoutDashboard],
  ["/create", "创建教学材料", Sparkles],
  ["/materials", "教学资料", FolderOpen],
  ["/jobs", "生成任务", ListChecks],
  ["/results", "生成成果", FileCheck2],
];
function Icon({
  icon: Component,
  size = 20,
}: {
  icon: LucideIcon;
  size?: number;
}) {
  return <Component size={size} strokeWidth={1.8} aria-hidden="true" />;
}
function Spinner({ text = "正在加载…" }: { text?: string }) {
  return (
    <div className="loading">
      <Loader2 className="spin" size={23} />
      <span>{text}</span>
    </div>
  );
}
function Badge({ status }: { status: string }) {
  return (
    <span className={`badge ${status}`}>
      <span />
      {statusNames[status] || status}
    </span>
  );
}
function ErrorBox({ text, retry }: { text: string; retry?: () => void }) {
  return (
    <div className="notice error" role="alert">
      <CircleAlert size={19} />
      <span>{text}</span>
      {retry && (
        <button className="text-button" onClick={retry}>
          重新加载
        </button>
      )}
    </div>
  );
}
function Empty({
  icon = FolderOpen,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon icon={icon} size={30} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "Tab") {
        const nodes = ref.current?.querySelectorAll<HTMLElement>(
          'button,a,input,textarea,select,[tabindex="0"]',
        );
        if (!nodes?.length) return;
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      previous?.focus();
    };
  }, [close]);
  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        className="modal"
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="modal-header">
          <h2 id="modal-title">{title}</h2>
          <button className="icon-button" aria-label="关闭" onClick={close}>
            <X />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Login({ done }: { done: () => void }) {
  const [token, setToken] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <div className="login-page">
      <div className="login-card">
        <div className="brand-mark">
          <GraduationCap size={30} />
        </div>
        <span className="eyebrow">CLAW-ED · 教学工作台</span>
        <h1>让备课，更从容。</h1>
        <p>连接你的本地工作台，开始整理资料与创建教学材料。</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api("/workbench/session", {
                method: "POST",
                body: JSON.stringify({ token }),
              });
              setToken("");
              done();
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="field">
            本地访问令牌
            <input
              type="password"
              autoComplete="off"
              value={token}
              required
              onChange={(e) => setToken(e.target.value)}
              placeholder="粘贴本机访问令牌"
            />
          </label>
          {error && <ErrorBox text={error} />}
          <button className="button primary wide" disabled={busy}>
            {busy ? (
              <Loader2 className="spin" size={18} />
            ) : (
              <ShieldCheck size={18} />
            )}
            进入工作台
          </button>
        </form>
        <details className="login-help">
          <summary>在哪里找到访问令牌？</summary>
          <p>在本机 PowerShell 终端运行：</p>
          <code>Get-Content "$env:USERPROFILE\.eduagent\api_token"</code>
          <p>
            这是本地网页访问令牌，与 DeepSeek API Key 不同。若设置了
            EDUAGENT_DATA_DIR，请到该目录查看 api_token。
          </p>
        </details>
      </div>
      <span className="login-footer">
        你的资料，本地保存 · 由你选择的模型协助生成
      </span>
    </div>
  );
}

function App() {
  const [auth, setAuth] = useState(false),
    [menu, setMenu] = useState(false),
    [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const overview = useLoad<Overview>("/workbench/overview", auth ? 0 : 8000);
  const location = useLocation();
  useEffect(() => {
    const handler = () => setAuth(true);
    window.addEventListener("auth-required", handler);
    return () => window.removeEventListener("auth-required", handler);
  }, []);
  useEffect(() => {
    setMenu(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 5000);
    return () => window.clearTimeout(timer);
  }, [toast]);
  const notify = useCallback(
    (text: string, error = false) => setToast({ text, error }),
    [],
  );
  if (auth)
    return (
      <Login
        done={() => {
          setAuth(false);
          overview.reload();
        }}
      />
    );
  const current = location.pathname.includes("/jobs/")
    ? "任务详情"
    : [
        ...navItems,
        ["/settings", "模型设置", Settings2] as [string, string, LucideIcon],
      ].find(
        ([path]) =>
          location.pathname === "/app" + path ||
          location.pathname === "/app" + path + "/",
      )?.[1] || "教学工作台";
  return (
    <AppContext.Provider
      value={{ overview: overview.data, refresh: overview.reload, notify }}
    >
      {menu && (
        <div className="sidebar-overlay" onClick={() => setMenu(false)} />
      )}
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <Link className="brand" to="/app">
          <span className="brand-mark">
            <GraduationCap size={26} />
          </span>
          <span>
            Claw-ED<small>中文教学工作台</small>
          </span>
        </Link>
        <div className="nav-caption">教学空间</div>
        <nav>
          {navItems.map(([path, name, icon]) => (
            <NavLink
              end={!path}
              key={path}
              to={"/app" + path}
              className={({ isActive }) =>
                `nav-item ${isActive ? "active" : ""}`
              }
            >
              <Icon icon={icon} />
              <span>{name}</span>
              {path === "/jobs" && !!overview.data?.active && (
                <span className="nav-count">{overview.data.active}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <NavLink
            to="/app/settings"
            className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
          >
            <Settings2 size={20} />
            模型设置
          </NavLink>
          <details className="more-menu">
            <summary className="nav-item">
              <MoreHorizontal size={20} />
              更多功能
              <ChevronDown size={15} />
            </summary>
            <a href="/dashboard" target="_blank" rel="noreferrer">
              原版教学面板 ↗
            </a>
            <a href="/students" target="_blank" rel="noreferrer">
              学生管理 ↗
            </a>
            <a href="/analytics" target="_blank" rel="noreferrer">
              教学统计 ↗
            </a>
          </details>
          <div className="local-card">
            <ShieldCheck size={18} />
            <div>
              本地教学空间<small>资料与成果保存在本机</small>
            </div>
          </div>
          <div className="user-card">
            <span className="avatar">
              {overview.data?.teacher_name?.slice(0, 1) || "教"}
            </span>
            <div>
              {overview.data?.teacher_name || "老师"}
              <small>我的教学工作台</small>
            </div>
            {overview.data?.auth_required && (
              <button
                className="icon-button"
                title="退出登录"
                aria-label="退出登录"
                onClick={async () => {
                  try {
                    await api("/workbench/session", { method: "DELETE" });
                    setAuth(true);
                  } catch (e) {
                    notify((e as Error).message, true);
                  }
                }}
              >
                <LogOut size={16} />
              </button>
            )}
          </div>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="打开导航"
              onClick={() => setMenu(true)}
            >
              <Menu />
            </button>
            <span>我的教学空间</span>
            <ChevronRight size={14} />
            <strong>{current}</strong>
          </div>
          <div className="topbar-right">
            <Link to="/app/settings" className="model-pill">
              <span
                className={`dot ${overview.data?.has_key ? "green" : ""}`}
              />
              {overview.data?.model || "模型配置"}
              <ChevronDown size={13} />
            </Link>
            <span className="top-date">
              {new Date().toLocaleDateString("zh-CN", {
                timeZone: "Asia/Shanghai",
                month: "long",
                day: "numeric",
                weekday: "long",
              })}
            </span>
          </div>
        </header>
        <main className="page">
          <Routes>
            <Route path="/app" element={<Dashboard />} />
            <Route path="/app/create" element={<CreatePage />} />
            <Route path="/app/materials" element={<MaterialsPage />} />
            <Route path="/app/jobs" element={<JobsPage />} />
            <Route path="/app/jobs/:id" element={<JobDetail />} />
            <Route path="/app/results" element={<ResultsPage />} />
            <Route path="/app/settings" element={<SettingsPage />} />
            <Route
              path="*"
              element={
                <Empty
                  title="这个页面不存在"
                  description="返回工作台，继续准备你的课程。"
                  action={
                    <Link to="/app" className="button primary">
                      返回工作台
                    </Link>
                  }
                />
              }
            />
          </Routes>
          <footer className="page-footer">
            <span>Claw-ED · 为每一节好课留出更多时间</span>
            <span>
              <span
                className={`dot ${overview.data?.worker_online ? "green" : ""}`}
              />
              {overview.data?.worker_online
                ? "任务处理服务在线"
                : "任务处理服务未连接"}
            </span>
          </footer>
        </main>
      </div>
      {toast && (
        <div className={`toast ${toast.error ? "error" : ""}`} role="status">
          {toast.error ? <CircleAlert size={19} /> : <CheckCircle2 size={19} />}
          {toast.text}
          <button
            className="icon-button"
            aria-label="关闭提示"
            onClick={() => setToast(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}
    </AppContext.Provider>
  );
}

function ManageButton({
  job,
  target,
  restore = false,
  done,
}: {
  job: Job;
  target: "record" | "results" | "both";
  restore?: boolean;
  done: () => void;
}) {
  const { notify, refresh } = useContext(AppContext);
  const [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [both, setBoth] = useState(false);
  const close = useCallback(() => {
    if (!busy) setOpen(false);
  }, [busy]);
  if (["queued", "running", "cancel_requested"].includes(job.status))
    return null;
  const label = restore
    ? "恢复"
    : target === "record"
      ? "删除记录"
      : "删除成果";
  return (
    <>
      <button
        className={`text-button ${restore ? "" : "danger-text"}`}
        onClick={() => setOpen(true)}
      >
        {label}
      </button>
      {open && (
        <Modal title={restore ? "恢复已删除内容" : label} close={close}>
          <div className="manage-content">
            <h3>{job.payload.topic}</h3>
            <p>
              {restore
                ? "恢复该课程已删除的任务记录和成果。"
                : target === "record"
                  ? "删除后任务记录移入回收站，生成成果默认保留。"
                  : "生成成果移入回收站，任务记录保留。"}
            </p>
            <p>文件保留在本机，可在“生成成果 → 回收站”恢复。</p>
            {target === "record" && !restore && (
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={both}
                  onChange={(e) => setBoth(e.target.checked)}
                />
                同时删除生成成果
              </label>
            )}
            {(target !== "record" || both) && (
              <ul>
                {job.result?.files?.map((file) => (
                  <li key={file}>{fileName(file)}</li>
                ))}
              </ul>
            )}
            <div className="button-row">
              <button
                className="button secondary"
                onClick={close}
                disabled={busy}
              >
                取消
              </button>
              <button
                className="button primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api(`/workbench/jobs/${job.id}/manage`, {
                      method: "POST",
                      body: JSON.stringify({
                        target: both ? "both" : target,
                        restore,
                      }),
                    });
                    notify(restore ? "已恢复。" : "已移入回收站，可随时恢复。");
                    setOpen(false);
                    done();
                    refresh();
                  } catch (e) {
                    notify((e as Error).message, true);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "处理中…" : restore ? "确认恢复" : "确认移入回收站"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

function JobsTable({ jobs }: { jobs: Job[] }) {
  return (
    <div className="table-scroll">
      <table className="jobs-table">
        <thead>
          <tr>
            <th>课程 / 任务名称</th>
            <th>教学对象</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>
              <span className="sr-only">操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>
                <Link to={"/app/jobs/" + job.id} className="table-title">
                  <span className="file-symbol">
                    <FileText size={19} />
                  </span>
                  <span>
                    {job.result?.title || job.payload.topic || "教学材料任务"}
                    <small>
                      {job.payload.subject || "课程材料"} ·{" "}
                      {(job.payload.outputs || ["teacher", "student", "slides"])
                        .map((v) => outputNames[v as Output])
                        .join(" / ")}
                    </small>
                  </span>
                </Link>
              </td>
              <td>{job.payload.grade || "—"}</td>
              <td>
                <Badge status={job.status} />
              </td>
              <td className="muted nowrap">{dateTime(job.created_at)}</td>
              <td>
                <Link className="text-button nowrap" to={"/app/jobs/" + job.id}>
                  查看
                  <ChevronRight size={14} />
                </Link>
                <ManageButton
                  job={job}
                  target="record"
                  done={() => window.dispatchEvent(new Event("jobs-changed"))}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Dashboard() {
  const { overview } = useContext(AppContext);
  const jobs = useLoad<Job[]>("/jobs", 8000);
  const stats: [string, number, LucideIcon, string][] = [
    ["教学资料", overview?.materials || 0, FolderOpen, "blue"],
    ["生成任务", overview?.jobs || 0, ListChecks, "violet"],
    ["进行中", overview?.active || 0, Clock3, "orange"],
    ["已生成文件", overview?.files || 0, FileCheck2, "green"],
  ];
  return (
    <>
      <PageHeader
        eyebrow="准备好，开启一节好课"
        title={`${overview?.teacher_name || "老师"}，欢迎回来`}
        description="把重复的整理交给 AI，把更多时间留给教学本身。"
        action={
          <Link className="button primary" to="/app/create">
            <Plus size={18} />
            创建教学材料
          </Link>
        }
      />
      <section className="welcome-card">
        <div className="welcome-copy">
          <span className="welcome-label">
            <Sparkles size={15} />
            你的 AI 备课助手
          </span>
          <h2>从一个想法，到一堂好课。</h2>
          <p>
            输入课程内容，结合你的教学资料，
            <br />
            一次生成教案、学生讲义和教学课件。
          </p>
          <div className="button-row">
            <Link to="/app/create" className="button primary">
              开始备课
              <ArrowRight size={17} />
            </Link>
            <Link to="/app/materials" className="button white">
              <Upload size={17} />
              上传教学资料
            </Link>
          </div>
        </div>
        <div className="welcome-art" aria-hidden="true">
          <div className="art-dots" />
          <div className="art-sheet back">
            <div className="art-label">
              <Presentation size={16} />
              教学课件
            </div>
            <div className="art-chart">
              <i />
              <i />
              <i />
              <i />
            </div>
          </div>
          <div className="art-sheet front">
            <div className="art-label">
              <FileText size={16} />
              教学设计
            </div>
            <div className="art-line long" />
            <div className="art-line" />
            <div className="art-tick">
              <Check size={13} />
              明确的教学目标
            </div>
            <div className="art-tick">
              <Check size={13} />
              丰富的课堂活动
            </div>
            <div className="art-tick">
              <Check size={13} />
              完整的教学材料
            </div>
          </div>
          <span className="art-spark">
            <Sparkles size={26} />
          </span>
        </div>
      </section>
      <div className="stats-grid">
        {stats.map(([label, value, icon, color]) => (
          <div className="stat-card" key={label}>
            <div>
              <span>{label}</span>
              <strong>
                {value}
                <small>{label === "已生成文件" ? "份" : "项"}</small>
              </strong>
            </div>
            <span className={`stat-icon ${color}`}>
              <Icon icon={icon} size={23} />
            </span>
          </div>
        ))}
      </div>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>最近任务</h2>
              <p>随时接着上次的备课进度</p>
            </div>
            <Link to="/app/jobs" className="text-button">
              全部任务
              <ArrowRight size={15} />
            </Link>
          </div>
          {jobs.error ? (
            <ErrorBox text={jobs.error} retry={jobs.reload} />
          ) : jobs.loading ? (
            <Spinner />
          ) : jobs.data?.length ? (
            <JobsTable jobs={jobs.data.slice(0, 5)} />
          ) : (
            <Empty
              title="从第一份教学材料开始"
              description="填写课程主题和教学要求，即可创建你的第一个任务。"
              action={
                <Link to="/app/create" className="button primary">
                  <Plus size={17} />
                  创建任务
                </Link>
              }
            />
          )}
        </section>
        <aside className="panel guide-card">
          <div className="panel-heading">
            <h2>三步，轻松备课</h2>
            <BookOpen size={20} />
          </div>
          {[
            [
              "整理教学资料",
              "上传教材、课件或讲义，让生成内容更贴近你的课程。",
            ],
            ["说明教学要求", "设置主题、教学对象与课时，选择需要的材料。"],
            ["审核并下载成果", "查看教学方案与生成文件，确认后用于课堂。"],
          ].map(([title, text], i) => (
            <div className="guide-step" key={title}>
              <span>{i + 1}</span>
              <div>
                <h3>{title}</h3>
                <p>{text}</p>
              </div>
            </div>
          ))}
          <div className="guide-note">
            <HelpCircle size={17} />
            <p>
              生成内容由你选定的模型提供。使用前，请审核事实、答案与课堂安排。
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}

type Draft = {
  topic: string;
  subject: string;
  grade: string;
  duration_minutes: number;
  content: string;
  requirements: string;
  material_ids: string[];
  outputs: Output[];
  include_images: boolean;
  include_homework: boolean;
  teacher_template_id: string;
  student_template_id: string;
  ppt_template_id: string;
};
const initialDraft: Draft = {
  topic: "",
  subject: "",
  grade: "本科生",
  duration_minutes: 45,
  content: "",
  requirements: "",
  material_ids: [],
  outputs: ["teacher", "student", "slides"],
  include_images: false,
  include_homework: true,
  teacher_template_id: "",
  student_template_id: "",
  ppt_template_id: "",
};
function CreatePage() {
  const templates = useLoad<WordTemplate[]>("/workbench/templates");
  const pptTemplates = useLoad<PptTemplate[]>("/workbench/ppt/templates");
  const { overview, notify, refresh } = useContext(AppContext);
  const materials = useLoad<Material[]>("/workbench/materials");
  const [draft, setDraft] = useState<Draft>(() => {
    try {
      return {
        ...initialDraft,
        ...JSON.parse(sessionStorage.getItem("clawed-draft") || "{}"),
      };
    } catch {
      return initialDraft;
    }
  });
  const [busy, setBusy] = useState(false);
  const form = useRef<HTMLFormElement>(null),
    navigate = useNavigate();
  const update = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((v) => ({ ...v, [key]: value }));
  useEffect(() => {
    sessionStorage.setItem("clawed-draft", JSON.stringify(draft));
  }, [draft]);
  const toggleOutput = (role: Output) =>
    update(
      "outputs",
      draft.outputs.includes(role)
        ? draft.outputs.filter((v) => v !== role)
        : [...draft.outputs, role],
    );
  const submit = async () => {
    if (!draft.outputs.length) {
      notify("请至少选择一种输出材料。", true);
      return;
    }
    setBusy(true);
    try {
      const result = await api<{ id: string }>("/jobs", {
        method: "POST",
        body: JSON.stringify({ ...draft, workbench: true }),
      });
      sessionStorage.removeItem("clawed-draft");
      refresh();
      notify("任务已创建，正在准备生成。");
      navigate("/app/jobs/" + result.id);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHeader
        eyebrow="让教学想法落地"
        title="创建教学材料"
        description="告诉我们这节课的内容和要求，剩下的交给你的 AI 助手。"
      />
      <div className="create-layout">
        <div>
          <form
            ref={form}
            className="panel form-panel"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            {
              <>
                <div className="section-heading">
                  <span className="section-icon">
                    <BookOpen size={21} />
                  </span>
                  <div>
                    <h2>这节课，你想教什么？</h2>
                    <p>清楚的课程信息，能帮助模型做出更合适的教学设计。</p>
                  </div>
                </div>
                <label className="field">
                  课程主题 <em>*</em>
                  <input
                    value={draft.topic}
                    onChange={(e) => update("topic", e.target.value)}
                    required
                    maxLength={500}
                    placeholder=""
                  />
                </label>
                <div className="form-grid">
                  <label className="field">
                    学科 / 课程 <em>*</em>
                    <input
                      value={draft.subject}
                      onChange={(e) => update("subject", e.target.value)}
                      required
                      maxLength={100}
                      placeholder=""
                      list="subject-list"
                    />
                    <datalist id="subject-list">
                      {[
                        "语文",
                        "数学",
                        "英语",
                        "物理",
                        "化学",
                        "生物",
                        "历史",
                        "计算机科学",
                        "人工智能",
                      ].map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </datalist>
                  </label>
                  <label className="field">
                    教学对象 <em>*</em>
                    <input
                      value={draft.grade}
                      onChange={(e) => update("grade", e.target.value)}
                      required
                      maxLength={20}
                      list="grade-list"
                      placeholder=""
                    />
                    <datalist id="grade-list">
                      {[
                        "小学",
                        "初中",
                        "高中",
                        "高职学生",
                        "本科生",
                        "研究生",
                      ].map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </datalist>
                  </label>
                </div>
                <label className="field narrow">
                  课时长度（分钟）
                  <input
                    type="number"
                    value={draft.duration_minutes}
                    onChange={(e) =>
                      update("duration_minutes", Number(e.target.value))
                    }
                    required
                    min={15}
                    max={240}
                    step={5}
                  />
                </label>
                <label className="field">
                  课程内容
                  <textarea
                    rows={7}
                    value={draft.content}
                    maxLength={50000}
                    onChange={(e) => update("content", e.target.value)}
                    placeholder="可以粘贴课程大纲、知识点或讲解内容。也可以在下方选择教学资料。"
                  />
                  <span className="field-hint">
                    内容越具体，生成的教学材料越贴近你的课堂。
                    {draft.content.length.toLocaleString()} / 50,000 字符
                  </span>
                </label>
              </>
            }
            {
              <>
                <div className="section-heading">
                  <span className="section-icon">
                    <FolderOpen size={21} />
                  </span>
                  <div>
                    <h2>结合你的资料，明确教学要求</h2>
                    <p>只有你选中的资料会作为本次任务的参考内容。</p>
                  </div>
                </div>
                <div className="label-row">
                  <h3>选择教学资料</h3>
                  <Link to="/app/materials" className="text-button">
                    <Plus size={15} />
                    上传新资料
                  </Link>
                </div>
                {materials.error ? (
                  <ErrorBox text={materials.error} retry={materials.reload} />
                ) : materials.loading ? (
                  <Spinner />
                ) : materials.data?.length ? (
                  <div className="material-picker">
                    {materials.data.map((item) => (
                      <label
                        key={item.id}
                        className={`pick-row ${draft.material_ids.includes(item.id) ? "selected" : ""}`}
                      >
                        <input
                          type="checkbox"
                          checked={draft.material_ids.includes(item.id)}
                          disabled={item.status !== "ready"}
                          onChange={(e) =>
                            update(
                              "material_ids",
                              e.target.checked
                                ? [...draft.material_ids, item.id]
                                : draft.material_ids.filter(
                                    (v) => v !== item.id,
                                  ),
                            )
                          }
                        />
                        <span className="file-symbol">
                          <FileText size={20} />
                        </span>
                        <span>
                          {item.name}
                          <small>
                            {item.status === "ready"
                              ? `${item.characters.toLocaleString()} 字符 · ${sizeText(item.size)}`
                              : item.status === "failed"
                                ? "解析失败"
                                : "正在解析"}
                          </small>
                        </span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="inline-empty">
                    尚未上传资料。可以直接根据课程内容生成，也可以先
                    <Link to="/app/materials">上传教材</Link>。
                  </div>
                )}
                <label className="field spaced">
                  教学目标与特殊要求
                  <textarea
                    rows={5}
                    maxLength={6000}
                    value={draft.requirements}
                    onChange={(e) => update("requirements", e.target.value)}
                    placeholder=""
                  />
                </label>
                <h3 className="field-title">选择输出材料</h3>
                <div className="output-options">
                  {(["teacher", "student", "slides"] as Output[]).map(
                    (role) => (
                      <label
                        className={`output-option ${draft.outputs.includes(role) ? "selected" : ""}`}
                        key={role}
                      >
                        <input
                          type="checkbox"
                          checked={draft.outputs.includes(role)}
                          onChange={() => toggleOutput(role)}
                        />
                        <Icon
                          icon={role === "slides" ? Presentation : FileText}
                          size={24}
                        />
                        <strong>{outputNames[role]}</strong>
                        <small>
                          {role === "slides" ? "可编辑 PPTX" : "可编辑 DOCX"}
                        </small>
                      </label>
                    ),
                  )}
                </div>
                <div className="section-heading">
                  <div>
                    <h2>选择 Word 模板</h2>
                    <p>模板决定栏目和内容组织方式；未选择时使用默认格式。</p>
                  </div>
                </div>
                {templates.error ? (
                  <ErrorBox text={templates.error} retry={templates.reload} />
                ) : (
                  <div className="form-grid">
                    {(["teacher", "student"] as const)
                      .filter((role) => draft.outputs.includes(role))
                      .map((role) => (
                        <TemplateSelect
                          key={role}
                          role={role}
                          value={draft[`${role}_template_id`]}
                          templates={templates.data || []}
                          onChange={(value) =>
                            update(`${role}_template_id`, value)
                          }
                        />
                      ))}
                  </div>
                )}
                <Link to="/app/materials?tab=templates" className="text-button">
                  上传与管理 Word 模板 <ArrowRight size={15} />
                </Link>
                {draft.outputs.includes("slides") && (
                  <>
                    <div className="section-heading">
                      <div>
                        <h2>选择 PPT 模板</h2>
                        <p>
                          按课程与模板组织每页内容；未选择时使用课堂清晰版。
                        </p>
                      </div>
                    </div>
                    {pptTemplates.error ? (
                      <ErrorBox
                        text={pptTemplates.error}
                        retry={pptTemplates.reload}
                      />
                    ) : (
                      <PptSelect
                        templates={pptTemplates.data || []}
                        value={draft.ppt_template_id}
                        onChange={(value) => update("ppt_template_id", value)}
                      />
                    )}
                    <Link to="/app/materials?tab=ppt" className="text-button">
                      上传与管理 PPT 模板 <ArrowRight size={15} />
                    </Link>
                  </>
                )}
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={draft.include_homework}
                    onChange={(e) =>
                      update("include_homework", e.target.checked)
                    }
                  />
                  允许安排课后作业（仍以教学要求为准）
                </label>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={draft.include_images}
                    onChange={(e) => update("include_images", e.target.checked)}
                  />
                  检索 Word 教学配图
                  <span className="muted">
                    用于默认格式教案与讲义；PPT 保留模板自带图片
                  </span>
                </label>
              </>
            }
            <div className="form-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => navigate("/app")}
                disabled={busy}
              >
                <ArrowLeft size={16} />
                返回工作台
              </button>
              <button
                type="submit"
                className="button primary"
                disabled={busy || !overview?.has_key}
              >
                {busy ? (
                  <Loader2 className="spin" size={17} />
                ) : (
                  <Sparkles size={17} />
                )}
                {busy ? "正在创建任务…" : "开始生成教学材料"}
              </button>
            </div>
          </form>
        </div>
        <aside className="create-aside">
          <div className="panel">
            <span className="aside-icon">
              <Sparkles size={24} />
            </span>
            <h3>本次生成</h3>
            <p>
              <strong>{draft.topic || "尚未填写课程主题"}</strong>
            </p>
            <p>
              {draft.subject || "待填写学科"} · {draft.grade} ·{" "}
              {draft.duration_minutes} 分钟
            </p>
            <p>已选 {draft.material_ids.length} 份参考资料</p>
            <p>
              {draft.outputs.map((v) => outputNames[v]).join("、") ||
                "请至少选择一种材料"}
            </p>
            <p>
              教案格式：
              {templates.data?.find((t) => t.id === draft.teacher_template_id)
                ?.name || "默认格式"}
            </p>
            <p>
              讲义格式：
              {templates.data?.find((t) => t.id === draft.student_template_id)
                ?.name || "默认格式"}
            </p>
            <p className="field-hint">已自动保存本页草稿</p>
            {!overview?.has_key && (
              <p className="error-box">
                请先<Link to="/app/settings">配置模型密钥</Link>。
              </p>
            )}
            <div className="aside-separator" />
            <h3>好材料，从清晰的要求开始</h3>
            <p>可以告诉 AI：</p>
            <ul>
              <li>学生已经掌握了哪些知识</li>
              <li>本节课最希望解决的问题</li>
              <li>喜欢怎样的案例和课堂活动</li>
              <li>练习与作业的难度要求</li>
            </ul>
            <div className="aside-separator" />
            <span className="small-label">本次生成模型</span>
            <strong className="aside-model">
              {overview?.model || "尚未读取"}
            </strong>
            <Link className="text-button" to="/app/settings">
              调整模型设置
              <ArrowRight size={14} />
            </Link>
          </div>
          <p className="aside-footnote">
            <ShieldCheck size={16} />
            资料保存在本机，生成时所选内容会发送至你配置的模型服务。
          </p>
        </aside>
      </div>
    </>
  );
}

function MaterialsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { notify } = useContext(AppContext);
  const templates =
    new URLSearchParams(location.search).get("tab") === "templates";
  const ppt = new URLSearchParams(location.search).get("tab") === "ppt";
  return (
    <>
      <div className="tabs material-tabs">
        <button
          className={!templates && !ppt ? "active" : ""}
          onClick={() => navigate("/app/materials")}
        >
          课程资料
        </button>
        <button
          className={templates ? "active" : ""}
          onClick={() => navigate("/app/materials?tab=templates")}
        >
          Word 模板
        </button>
        <button
          className={ppt ? "active" : ""}
          onClick={() => navigate("/app/materials?tab=ppt")}
        >
          PPT 模板
        </button>
      </div>
      {ppt ? (
        <PptTemplateLibrary notify={notify} />
      ) : templates ? (
        <TemplateLibrary
          notify={notify}
          initialId={new URLSearchParams(location.search).get("template") || ""}
        />
      ) : (
        <CourseMaterialsPage />
      )}
    </>
  );
}
function CourseMaterialsPage() {
  const navigate = useNavigate();
  const [trash, setTrash] = useState(false);
  const materials = useLoad<Material[]>(
    "/workbench/materials" + (trash ? "?trash=true" : ""),
  );
  const { notify, refresh } = useContext(AppContext);
  const [search, setSearch] = useState(""),
    [busy, setBusy] = useState(false),
    [drag, setDrag] = useState(false),
    [preview, setPreview] = useState<Material | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const [managing, setManaging] = useState(""),
    [removed, setRemoved] = useState<Material | null>(null);
  const manage = async (item: Material, deleted: boolean) => {
    setManaging(item.id);
    try {
      await api(`/workbench/materials/${item.id}/visibility`, {
        method: "POST",
        body: JSON.stringify({ deleted }),
      });
      setRemoved(deleted ? item : null);
      materials.reload();
      refresh();
      notify(
        deleted
          ? "资料已移至回收站，历史任务和成果保留。"
          : "资料已恢复，可以重新选择使用。",
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setManaging("");
    }
  };
  const close = useCallback(() => setPreview(null), []);
  const upload = async (files: FileList | null) => {
    if (!files?.length || busy) return;
    if (files.length > 20) {
      notify("每次最多上传 20 份资料。", true);
      return;
    }
    if (Array.from(files).some((file) => file.size > 50 * 1024 * 1024)) {
      notify("单份资料不能超过 50 MB。", true);
      return;
    }
    const data = new FormData();
    Array.from(files).forEach((file) => data.append("files", file));
    setBusy(true);
    try {
      const result = await api<{ materials: Material[] }>(
        "/workbench/materials",
        { method: "POST", body: data },
      );
      const failed = result.materials.filter(
        (v) => v.status === "failed",
      ).length;
      notify(
        failed
          ? `上传完成，${failed} 份资料需要检查解析结果。`
          : `已上传并解析 ${result.materials.length} 份资料。`,
        !!failed,
      );
      materials.reload();
      refresh();
    } catch (e) {
      notify((e as Error).message, true);
      materials.reload();
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  const filtered = (materials.data || []).filter((v) =>
    v.name.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeader
        eyebrow="让资料成为备课的起点"
        title="教学资料"
        description="整理教材、已有课件和讲义，作为课程内容参考。Word 格式模板请在另一个分类中管理。"
        action={
          !trash ? (
            <button
              className="button primary"
              disabled={busy}
              onClick={() => input.current?.click()}
            >
              <Plus size={18} />
              上传资料
            </button>
          ) : undefined
        }
      />
      <input
        ref={input}
        className="sr-only"
        type="file"
        multiple
        accept=".pdf,.docx,.pptx,.txt,.md"
        aria-label="选择教学资料文件"
        onChange={(e) => void upload(e.target.files)}
      />
      {!trash && (
        <button
          className={`upload-zone ${drag ? "drag" : ""} ${busy ? "busy" : ""}`}
          disabled={busy}
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            void upload(e.dataTransfer.files);
          }}
        >
          <span className="upload-symbol">
            {busy ? (
              <Loader2 size={28} className="spin" />
            ) : (
              <Upload size={28} />
            )}
          </span>
          <h2>{busy ? "正在上传并解析资料…" : "拖拽文件到这里，或点击上传"}</h2>
          <p>
            {busy
              ? "正在提取文档中的文字，请保持页面打开。"
              : "支持 PDF、Word、PowerPoint、TXT 和 Markdown"}
          </p>
          <span>单份文件不超过 50 MB，每次最多 20 份</span>
        </button>
      )}
      <div className="button-row library-tabs">
        <button
          className={`button ${!trash ? "primary" : "secondary"}`}
          disabled={busy || !!managing}
          onClick={() => setTrash(false)}
        >
          课程资料
        </button>
        <button
          className={`button ${trash ? "primary" : "secondary"}`}
          disabled={busy || !!managing}
          onClick={() => setTrash(true)}
        >
          <Trash2 size={17} />
          回收站
        </button>
      </div>
      {removed && (
        <div className="notice soft">
          <span>已删除“{removed.name}”，可在回收站恢复。</span>
          <button
            className="text-button"
            disabled={!!managing}
            onClick={() => void manage(removed, false)}
          >
            撤销删除
          </button>
        </div>
      )}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>
              {trash ? "资料回收站" : "我的资料"}{" "}
              <span className="count">{materials.data?.length || 0}</span>
            </h2>
            <p>
              {trash
                ? "恢复后即可重新用于备课；历史任务仍可读取原资料。"
                : "上传后自动解析，可删除不再使用的资料。"}
            </p>
          </div>
          <div className="search-field">
            <Search size={17} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索资料名称"
              aria-label="搜索资料名称"
            />
          </div>
        </div>
        {materials.error ? (
          <ErrorBox text={materials.error} retry={materials.reload} />
        ) : materials.loading ? (
          <Spinner />
        ) : !filtered.length ? (
          <Empty
            title={
              search
                ? "没有找到匹配的资料"
                : trash
                  ? "回收站为空"
                  : "给你的工作台添加第一份资料"
            }
            description={
              search
                ? "试试其他关键词。"
                : trash
                  ? "删除的课程资料会出现在这里，可随时恢复。"
                  : "上传教材或讲义，让 AI 根据你的课程内容设计材料。"
            }
          />
        ) : (
          <div className="table-scroll">
            <table className="jobs-table">
              <thead>
                <tr>
                  <th>资料名称</th>
                  <th>解析状态</th>
                  <th>文件大小</th>
                  <th>上传时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <div className="table-title">
                        <span
                          className={`file-symbol ${item.kind === "pptx" ? "orange" : ""}`}
                        >
                          {item.kind === "pptx" ? (
                            <Presentation size={20} />
                          ) : (
                            <FileText size={20} />
                          )}
                        </span>
                        <span>
                          {item.name}
                          <small>
                            {item.kind.toUpperCase()} ·{" "}
                            {item.characters?.toLocaleString() || 0} 字符
                          </small>
                        </span>
                      </div>
                    </td>
                    <td>
                      <span
                        className={`badge ${item.status === "ready" ? "done" : item.status === "failed" ? "failed" : "running"}`}
                      >
                        <span />
                        {item.status === "ready"
                          ? "已解析"
                          : item.status === "failed"
                            ? "解析失败"
                            : "解析中"}
                      </span>
                    </td>
                    <td className="muted">{sizeText(item.size)}</td>
                    <td className="muted nowrap">
                      {dateTime(item.created_at)}
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="text-button"
                          onClick={async () => {
                            try {
                              setPreview(
                                await api<Material>(
                                  "/workbench/materials/" + item.id,
                                ),
                              );
                            } catch (e) {
                              notify((e as Error).message, true);
                            }
                          }}
                        >
                          查看
                        </button>
                        {item.kind === "docx" && !trash && (
                          <button
                            className="text-button"
                            onClick={async () => {
                              try {
                                const template = await api<{ id: string }>(
                                  `/workbench/templates/from-material/${item.id}`,
                                  { method: "POST" },
                                );
                                notify("已复制到模板库，原课程资料保留。");
                                navigate(
                                  "/app/materials?tab=templates&template=" +
                                    template.id,
                                );
                              } catch (e) {
                                notify((e as Error).message, true);
                              }
                            }}
                          >
                            存为 Word 模板
                          </button>
                        )}
                        <a
                          className="icon-button"
                          title="下载原文件"
                          aria-label={`下载${item.name}`}
                          href={"/api/workbench/materials/" + item.id + "/file"}
                        >
                          <ArrowDownToLine size={17} />
                        </a>
                        <button
                          className={`text-button ${trash ? "" : "danger-text"}`}
                          aria-label={`${trash ? "恢复" : "删除"}${item.name}`}
                          disabled={busy || !!managing}
                          onClick={() => void manage(item, !trash)}
                        >
                          {trash ? <Undo2 size={16} /> : <Trash2 size={16} />}{" "}
                          {trash ? "恢复" : "删除"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <div className="notice soft">
        <HelpCircle size={18} />
        <span>
          扫描版 PDF
          需要先进行文字识别。较长的教材建议按章节上传，生成内容会更聚焦。
        </span>
      </div>
      {preview && (
        <Modal title={preview.name} close={close}>
          <div className="modal-body">
            <div className="tag-row">
              <span>{preview.kind.toUpperCase()}</span>
              <span>{preview.characters?.toLocaleString()} 字符</span>
              <a
                className="text-button"
                href={"/api/workbench/materials/" + preview.id + "/file"}
              >
                下载原文件
                <ArrowDownToLine size={15} />
              </a>
            </div>
            {preview.error ? (
              <ErrorBox text={preview.error} />
            ) : (
              <pre className="document-preview">
                {preview.text || "尚未提取到文字。"}
              </pre>
            )}
            {(preview.characters || 0) > 16000 && (
              <p className="muted">
                此处预览前 16,000 字符，完整原文件已保留。
              </p>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}

function JobsPage() {
  const jobs = useLoad<Job[]>("/jobs", 5000),
    { overview, notify } = useContext(AppContext);
  const [status, setStatus] = useState("all"),
    [search, setSearch] = useState(""),
    [recovering, setRecovering] = useState(false);
  const filtered = (jobs.data || []).filter(
    (item) =>
      (status === "all" ||
        (status === "active" &&
          ["queued", "running", "cancel_requested"].includes(item.status)) ||
        status === item.status) &&
      `${item.payload.topic} ${item.payload.subject}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeader
        eyebrow="每一步进度，清楚可见"
        title="生成任务"
        description="查看后台生成进度，管理任务，并从中断的位置继续。"
        action={
          <Link className="button primary" to="/app/create">
            <Plus size={18} />
            新建任务
          </Link>
        }
      />
      {overview && !overview.worker_online && (
        <div className="notice warning">
          <CircleAlert size={20} />
          <div>
            <strong>任务处理服务尚未上线</strong>
            <p>
              请启动后台服务，或在终端运行 clawed queue
              worker。排队任务会在处理服务上线后开始执行。
            </p>
          </div>
        </div>
      )}
      <section className="panel">
        <div className="list-toolbar">
          <div className="tabs">
            {[
              ["all", "全部任务"],
              ["active", "进行中"],
              ["done", "已完成"],
              ["failed", "需要处理"],
            ].map(([value, label]) => (
              <button
                className={status === value ? "active" : ""}
                key={value}
                onClick={() => setStatus(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="toolbar-actions">
            <div className="search-field">
              <Search size={17} />
              <input
                aria-label="搜索任务"
                placeholder="搜索课程或任务"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button
              className="icon-button"
              aria-label="刷新任务"
              title="刷新任务"
              onClick={jobs.reload}
            >
              <RefreshCw size={18} />
            </button>
          </div>
        </div>
        {jobs.error ? (
          <ErrorBox text={jobs.error} retry={jobs.reload} />
        ) : jobs.loading && !jobs.data ? (
          <Spinner />
        ) : filtered.length ? (
          <JobsTable jobs={filtered} />
        ) : (
          <Empty
            icon={ListChecks}
            title={
              search || status !== "all"
                ? "没有符合条件的任务"
                : "还没有生成任务"
            }
            description={
              search || status !== "all"
                ? "调整搜索条件，或查看其他任务状态。"
                : "从一个课程主题开始，创建你的第一份教学材料。"
            }
            action={
              !search &&
              status === "all" && (
                <Link to="/app/create" className="button primary">
                  创建教学材料
                  <ArrowRight size={16} />
                </Link>
              )
            }
          />
        )}
        <div className="list-footer">
          <span>共 {filtered.length} 项 · 进度每 5 秒自动更新</span>
          <button
            className="text-button"
            disabled={recovering}
            onClick={async () => {
              setRecovering(true);
              try {
                const r = await api<{ recovered: number }>("/jobs/recover", {
                  method: "POST",
                });
                notify(
                  r.recovered
                    ? `已标记 ${r.recovered} 个中断任务，可进入任务详情恢复。`
                    : "没有发现失去响应超过五分钟的任务。",
                );
                jobs.reload();
              } catch (e) {
                notify((e as Error).message, true);
              } finally {
                setRecovering(false);
              }
            }}
          >
            <RefreshCw size={14} />
            检查中断任务
          </button>
        </div>
      </section>
    </>
  );
}

const contentLabels: Record<string, string> = {
  answers: "参考答案",
  stimulus_type: "情境类型",
  hook_type: "导入方式",
  key_points: "关键知识点",
  hook: "导入提示",
  transition: "过渡说明",
  slide_summary: "课件摘要",
  prompt: "题目",
  section_ref: "对应教学环节",
  source_type: "资料类型",
  scaffolding_questions: "引导问题",
  slide_excerpt: "课件摘录",
  source_ref: "参考资料编号",
  source_refs: "参考资料编号",
  student_directions: "学生活动说明",
  teacher_answer_key: "教师参考答案",
  timer_minutes: "活动用时（分钟）",
  group_roles: "小组角色",
  reporting_template: "汇报格式",
  rubric_snippet: "评价标准",
  exemplar: "示范答案",
  cognitive_level: "认知层次",
  sentence_starters: "作答提示",
  response_framework: "作答框架",
  slide_stimulus: "课件情境",
  activity_type: "活动形式",
  debrief: "总结",
  debrief_question: "总结问题",
  deliverable: "活动成果",
  documents_per_group: "每组资料数",
  expert_phase_minutes: "专家组阶段（分钟）",
  graphic_organizer: "学习组织图",
  num_expert_groups: "专家组数",
  roles: "角色分工",
  scenario: "活动情境",
  share_out_protocol: "交流方式",
  teaching_phase_minutes: "分享阶段（分钟）",
  time_minutes: "时长（分钟）",
  reference: "参考内容",
  date: "日期",
  locator: "原文位置",
  origin: "来源",
  title: "标题",
  objective: "教学目标",
  duration_minutes: "课时",
  vocabulary: "核心概念",
  do_now: "课堂导入",
  direct_instruction: "知识讲解",
  guided_notes: "学习笔记",
  primary_sources: "参考资料",
  stations: "分组学习活动",
  independent_work: "独立练习",
  exit_ticket: "课堂检测",
  differentiation: "分层教学",
  homework: "课后作业",
  minute_by_minute: "教学安排",
  materials_needed: "教学准备",
  misconceptions: "常见误区",
  formative_checks: "过程性评价",
  prerequisite_skills: "先备知识",
  term: "概念",
  definition: "定义",
  context_sentence: "例句",
  heading: "主题",
  content: "内容",
  teacher_script: "教师讲解",
  stimulus: "情境",
  questions: "问题",
  question: "问题",
  answer: "参考答案",
  model_answer: "参考答案",
  learning_goal: "学习目标",
  task: "任务",
  instructions: "说明",
  struggling: "基础巩固",
  advanced: "拓展提升",
  ell: "语言支持",
  time: "时间",
  activity: "教学活动",
  teacher_moves: "教师活动",
  content_text: "资料原文",
  attribution: "来源",
  answer_key: "参考答案",
  text: "内容",
};
function ContentValue({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  if (value === null || value === undefined || value === "") return null;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const block = value as { kind?: string; text?: string; rows?: string[][] };
    if (
      ["paragraph", "heading", "formula", "table"].includes(block.kind || "")
    ) {
      if (block.kind === "table")
        return (
          <div className="template-content-table">
            {block.text && <p>{block.text}</p>}
            <table>
              <tbody>
                {block.rows?.map((row, i) => (
                  <tr key={i}>
                    {row.map((text, j) => (
                      <td key={j}>{text}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      if (block.kind === "heading") return <h4>{block.text}</h4>;
      return (
        <p
          className={block.kind === "formula" ? "template-formula" : "pre-wrap"}
        >
          {block.text}
        </p>
      );
    }
    if (
      Object.keys(value).length &&
      Object.keys(value).every((k) => /^s\d+$/.test(k))
    )
      return (
        <>
          {Object.values(value).map((v, i) => (
            <ContentValue key={i} value={v} depth={depth} />
          ))}
        </>
      );
  }
  if (Array.isArray(value))
    return (
      <div className="content-items">
        {value.map((item, i) => (
          <div className={depth ? "content-subitem" : "content-item"} key={i}>
            {typeof item === "object" && item ? (
              <span className="item-index">
                {String(i + 1).padStart(2, "0")}
              </span>
            ) : null}
            <ContentValue value={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  if (typeof value === "object")
    return (
      <div className="content-fields">
        {Object.entries(value as Record<string, unknown>)
          .filter(
            ([key, val]) =>
              ![
                "id",
                "image_spec",
                "source_manifest",
                "brain_context",
              ].includes(key) &&
              val != null &&
              val !== "" &&
              !(Array.isArray(val) && !val.length),
          )
          .map(([key, val]) => (
            <div key={key}>
              <span className="content-field-label">
                {contentLabels[key] || key}
              </span>
              <ContentValue value={val} depth={depth + 1} />
            </div>
          ))}
      </div>
    );
  return (
    <p className="pre-wrap">
      {String(value)
        .replace(/Do Now/g, "课堂导入")
        .replace(/Exit Ticket/g, "课堂检测")}
    </p>
  );
}
function JobDetail() {
  const { id } = useParams(),
    job = useLoad<Job>("/workbench/jobs/" + id, 5000),
    { notify, refresh } = useContext(AppContext);
  const navigate = useNavigate();
  const templates = useLoad<WordTemplate[]>("/workbench/templates");
  const pptTemplates = useLoad<PptTemplate[]>("/workbench/ppt/templates");
  const [reexportOpen, setReexportOpen] = useState(false);
  const [exportTemplates, setExportTemplates] = useState({
    teacher: "__original__",
    student: "__original__",
    ppt: "__original__",
  });
  const closeReexport = useCallback(() => setReexportOpen(false), []);
  const [busy, setBusy] = useState(false),
    [tab, setTab] = useState("overview");
  if (job.error)
    return (
      <>
        <Link className="back-link" to="/app/jobs">
          <ArrowLeft size={16} />
          返回任务列表
        </Link>
        <ErrorBox text={job.error} retry={job.reload} />
      </>
    );
  if (!job.data) return <Spinner text="正在读取任务…" />;
  const item = job.data,
    files = item.visibility?.results_deleted ? [] : item.result?.files || [],
    active = ["queued", "running", "cancel_requested"].includes(item.status),
    canResume = ["failed", "cancelled", "interrupted"].includes(item.status);
  const stage = item.events?.at(-1),
    content = item.content;
  const act = async (action: string) => {
    setBusy(true);
    try {
      await api("/jobs/" + id + "/" + action, { method: "POST" });
      notify(
        action === "cancel"
          ? "已请求取消，正在处理中的模型请求可能需要稍后停止。"
          : "任务已重新排队，已保存的匹配内容会被复用。",
      );
      job.reload();
      refresh();
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Link className="back-link" to="/app/jobs">
        <ArrowLeft size={16} />
        返回任务列表
      </Link>
      <PageHeader
        title={item.result?.title || item.payload.topic || "教学材料任务"}
        description={`任务 ${item.id} · 创建于 ${dateTime(item.created_at, true)}`}
        action={
          <div className="button-row">
            <Badge status={item.status} />
            {!active && content && (
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => setReexportOpen(true)}
              >
                重新导出文件
              </button>
            )}
            <ManageButton
              job={item}
              target="record"
              done={() => navigate("/app/jobs")}
            />
            {active && item.status !== "cancel_requested" && (
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => void act("cancel")}
              >
                取消任务
              </button>
            )}
            {canResume && (
              <button
                className="button primary"
                disabled={busy}
                onClick={() => void act("resume")}
              >
                <RefreshCw size={16} />
                恢复任务
              </button>
            )}
          </div>
        }
      />
      <div className="tag-row task-tags">
        <span>{item.payload.subject}</span>
        <span>{item.payload.grade}</span>
        {item.payload.duration_minutes && (
          <span>{item.payload.duration_minutes} 分钟</span>
        )}
        {item.result?.model && <span>{item.result.model}</span>}
      </div>
      {item.payload.reuse_task_id && (
        <p className="field-hint">
          本次以原任务的要求和已有内容为基础生成新版本。
          <Link to={"/app/jobs/" + item.payload.reuse_task_id}>查看原任务</Link>
        </p>
      )}
      {item.visibility?.results_deleted && (
        <div className="notice warning">
          成果已移入回收站。<Link to="/app/results">前往生成成果页面恢复</Link>
        </div>
      )}
      {item.visibility?.record_deleted && (
        <div className="notice soft">
          此任务记录已移入回收站，保留的成果仍可下载。
        </div>
      )}
      {item.error && <ErrorBox text={friendlyError(item.error)} />}
      {item.status === "failed" && files.length > 0 && (
        <div className="notice warning">
          <CircleAlert size={18} />
          <span>
            已有部分文件可下载，请查看提示。恢复任务可继续尝试未完成的部分。
          </span>
        </div>
      )}
      <div className={`detail-grid${tab === "ppt" && !active ? " ppt-focused" : ""}`}>
        <div>
          <section className="panel">
            <div className="tabs content-tabs">
              {[
                ["overview", "任务概览"],
                ...((
                  item.payload.outputs || ["teacher", "student", "slides"]
                ).includes("slides")
                  ? [["ppt", "课件预览"]]
                  : []),
                ["content", "教学内容"],
                [
                  "files",
                  `生成文件${files.length ? ` · ${files.length}` : ""}`,
                ],
              ].map(([key, label]) => (
                <button
                  className={tab === key ? "active" : ""}
                  onClick={() => setTab(key)}
                  key={key}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="detail-body">
              {tab === "overview" && (
                <>
                  <h2>任务要求</h2>
                  <dl className="task-description">
                    <dt>课程主题</dt>
                    <dd>{item.payload.topic}</dd>
                    <dt>输出材料</dt>
                    <dd>
                      {(
                        item.payload.outputs || ["teacher", "student", "slides"]
                      )
                        .map((role) => outputNames[role as Output])
                        .join("、")}
                    </dd>
                    {item.payload.word_templates &&
                      Object.keys(item.payload.word_templates).length > 0 && (
                        <>
                          <dt>Word 模板版本</dt>
                          <dd>
                            {Object.entries(item.payload.word_templates).map(
                              ([role, t]) => (
                                <p key={role}>
                                  {role === "teacher" ? "教师教案" : "学生讲义"}
                                  ：{t.name} · 第 {t.version} 版
                                </p>
                              ),
                            )}
                          </dd>
                        </>
                      )}
                    <dt>教学要求</dt>
                    <dd className="pre-wrap">
                      {item.payload.requirements ||
                        "根据本次任务和资料规划内容章节。"}
                    </dd>
                    <dt>参考资料</dt>
                    <dd>
                      {item.materials?.length
                        ? item.materials.map((v) => v.name).join("、")
                        : "输入的课程内容与主题"}
                    </dd>
                  </dl>
                  {item.payload.content && (
                    <>
                      <h3>课程内容</h3>
                      <div className="input-excerpt">
                        {item.payload.content}
                      </div>
                    </>
                  )}
                  {item.result?.objective && (
                    <div className="objective-box">
                      <span>
                        <Sparkles size={17} />
                        本次内容目标
                      </span>
                      <p>{item.result.objective}</p>
                    </div>
                  )}
                  {!!item.result?.warnings?.length && (
                    <div className="notice warning">
                      <CircleAlert size={18} />
                      <div>
                        {item.result.warnings.map((v) => (
                          <p key={v}>{v}</p>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
              {tab === "ppt" && (
                <PptViewer
                  key={item.id}
                  taskId={item.id}
                  notify={notify}
                  active={active}
                />
              )}
              {tab === "content" &&
                (content ? (
                  <>
                    <div className="notice soft">
                      <ShieldCheck size={17} />
                      <span>以下为本次生成的教学草稿，请核对后使用。</span>
                    </div>
                    {[
                      "任务说明",
                      "课件内容",
                      "任务理解",
                      "章节规划",
                      "章节内容",
                      "模板文档内容",
                      "模板教学方案",
                      "默认产物教学方案",
                      "objective",
                      "minute_by_minute",
                      "vocabulary",
                      "do_now",
                      "direct_instruction",
                      "guided_notes",
                      "primary_sources",
                      "stations",
                      "independent_work",
                      "exit_ticket",
                      "differentiation",
                      "homework",
                    ]
                      .filter(
                        (key) =>
                          content[key] &&
                          !(
                            Array.isArray(content[key]) &&
                            !(content[key] as unknown[]).length
                          ),
                      )
                      .map((key) => (
                        <section className="lesson-section" key={key}>
                          <h2>{contentLabels[key] || key}</h2>
                          <ContentValue value={content[key]} />
                        </section>
                      ))}
                  </>
                ) : (
                  <Empty
                    icon={BookOpen}
                    title="教学内容还在准备中"
                    description={
                      active
                        ? "生成并保存教学方案后，这里会显示内容摘要。"
                        : "此任务尚未保存可预览的结构化内容。"
                    }
                  />
                ))}
              {tab === "files" &&
                (files.length ? (
                  <>
                    <p className="muted">
                      文件可在 Word、PowerPoint 或 WPS 中打开和编辑。
                    </p>
                    <div className="download-list">
                      {files.map((file, i) => (
                        <a
                          className="download-row"
                          key={file}
                          href={`/api/jobs/${id}/files/${i}`}
                        >
                          <span
                            className={`file-symbol ${file.endsWith(".pptx") ? "orange" : ""}`}
                          >
                            {file.endsWith(".pptx") ? (
                              <Presentation />
                            ) : (
                              <FileText />
                            )}
                          </span>
                          <span>
                            <strong>{fileName(file)}</strong>
                            <small>
                              {file.endsWith(".pptx")
                                ? "可编辑 PowerPoint 课件"
                                : file.endsWith(".docx")
                                  ? "可编辑 Word 文档"
                                  : "生成附件"}
                            </small>
                          </span>
                          <ArrowDownToLine size={19} />
                        </a>
                      ))}
                    </div>
                  </>
                ) : (
                  <Empty
                    icon={FileCheck2}
                    title="文件尚未生成"
                    description="导出完成后，你可以在这里下载教学材料。"
                  />
                ))}
            </div>
          </section>
        </div>
        <aside>
          <section className="panel progress-panel">
            <div className="panel-heading">
              <h2>生成进度</h2>
              {active && <Loader2 className="spin muted" size={18} />}
            </div>
            <div className="current-stage">
              <span
                className={`dot ${active || item.status === "done" ? "green" : ""}`}
              />
              {item.status === "queued"
                ? "等待后台处理服务领取任务"
                : stage?.message || statusNames[item.status]}
            </div>
            <div className="timeline">
              <div className="timeline-item completed">
                <span className="timeline-dot">
                  <Check size={12} />
                </span>
                <div>
                  <strong>任务已创建</strong>
                  <small>{dateTime(item.created_at)}</small>
                </div>
              </div>
              {item.events?.map((e, i) => (
                <div
                  key={i}
                  className={`timeline-item ${i < (item.events?.length || 0) - 1 || !active ? "completed" : ""}`}
                >
                  <span className="timeline-dot">
                    {i < (item.events?.length || 0) - 1 || !active ? (
                      <Check size={12} />
                    ) : (
                      <span />
                    )}
                  </span>
                  <div>
                    <strong>{e.message}</strong>
                    <small>{dateTime(e.created_at)}</small>
                  </div>
                </div>
              ))}
            </div>
          </section>
          <div className="detail-help">
            <ShieldCheck size={20} />
            <p>任务在后台执行，离开页面不会停止生成。进度会自动更新。</p>
          </div>
        </aside>
      </div>
      {reexportOpen && (
        <Modal title="重新导出与更换模板" close={closeReexport}>
          <div className="manage-content">
            <p>
              课件优先由 Presenton 编排，教案与讲义依据实际课件整理。匹配的新版本课件可复用，原文件保留。
            </p>
            {templates.error && (
              <ErrorBox text={templates.error} retry={templates.reload} />
            )}
            {(["teacher", "student"] as const)
              .filter((role) =>
                (
                  item.payload.outputs || ["teacher", "student", "slides"]
                ).includes(role),
              )
              .map((role) => (
                <TemplateSelect
                  key={role}
                  role={role}
                  templates={templates.data || []}
                  value={exportTemplates[role]}
                  onChange={(value) =>
                    setExportTemplates((v) => ({ ...v, [role]: value }))
                  }
                  original
                />
              ))}
            {(
              item.payload.outputs || ["teacher", "student", "slides"]
            ).includes("slides") && (
              <PptSelect
                templates={pptTemplates.data || []}
                value={exportTemplates.ppt}
                original
                onChange={(value) =>
                  setExportTemplates((v) => ({ ...v, ppt: value }))
                }
              />
            )}
            <div className="button-row">
              <button
                className="button secondary"
                disabled={busy}
                onClick={closeReexport}
              >
                取消
              </button>
              <button
                className="button primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const body = Object.fromEntries(
                      Object.entries(exportTemplates)
                        .filter(([, v]) => v !== "__original__")
                        .map(([role, v]) => [role + "_template_id", v]),
                    );
                    const next = await api<{ id: string }>(
                      `/workbench/jobs/${id}/reexport`,
                      { method: "POST", body: JSON.stringify(body) },
                    );
                    setReexportOpen(false);
                    notify(
                      "已创建导出任务，将复用适用的内容并按所选模板处理。",
                    );
                    navigate("/app/jobs/" + next.id);
                    refresh();
                  } catch (e) {
                    notify((e as Error).message, true);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "正在创建…" : "开始重新导出"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

function ResultsPage() {
  const [trash, setTrash] = useState(false);
  const jobs = useLoad<Job[]>(
      "/workbench/results" + (trash ? "?trash=true" : ""),
      5000,
    ),
    [search, setSearch] = useState("");
  const results = (jobs.data || []).filter(
    (item) =>
      (trash || item.result?.files?.length) &&
      `${item.result?.title || ""} ${item.payload.topic}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeader
        eyebrow="每一次备课，都值得积累"
        title="生成成果"
        description="集中管理已生成的教案、课件和学生讲义，随时查看和下载。"
        action={
          <Link to="/app/create" className="button primary">
            <Plus size={18} />
            创建教学材料
          </Link>
        }
      />
      <div className="results-toolbar">
        <div className="button-row">
          <button
            className={`button ${!trash ? "primary" : "secondary"}`}
            onClick={() => setTrash(false)}
          >
            生成成果
          </button>
          <button
            className={`button ${trash ? "primary" : "secondary"}`}
            onClick={() => setTrash(true)}
          >
            回收站
          </button>
        </div>
        <p>
          共 <strong>{results.length}</strong> 组教学成果
        </p>
        <div className="search-field">
          <Search size={17} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索课程成果"
            aria-label="搜索课程成果"
          />
        </div>
      </div>
      {jobs.error ? (
        <ErrorBox text={jobs.error} retry={jobs.reload} />
      ) : jobs.loading && !jobs.data ? (
        <Spinner />
      ) : results.length ? (
        <div className="results-grid">
          {results.map((item) => (
            <article className="result-card" key={item.id}>
              <div className="result-cover">
                <div className="cover-document">
                  <FileText size={26} />
                  <span />
                  <span />
                  <span />
                </div>
                <div className="cover-slide">
                  <Presentation size={22} />
                  <div>
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
                <span className="cover-subject">{item.payload.subject}</span>
              </div>
              <div className="result-body">
                <div className="label-row">
                  <span className="small-label">
                    {item.payload.grade} · {dateTime(item.created_at)}
                  </span>
                  <Badge status={item.status} />
                </div>
                <Link to={"/app/jobs/" + item.id}>
                  <h2>{item.result?.title || item.payload.topic}</h2>
                </Link>
                <p className="result-objective">
                  {item.result?.objective || item.payload.topic}
                </p>
                {item.payload.reuse_task_id && (
                  <p className="field-hint">
                    重新导出的版本 ·{" "}
                    <Link to={"/app/jobs/" + item.payload.reuse_task_id}>
                      查看原任务
                    </Link>
                  </p>
                )}
                <div className="result-files">
                  {!item.visibility?.results_deleted &&
                    item.result?.files?.map((file, i) => (
                      <a
                        key={file}
                        href={`/api/jobs/${item.id}/files/${i}`}
                        title={`下载${fileName(file)}`}
                      >
                        <Icon
                          icon={
                            file.endsWith(".pptx") ? Presentation : FileText
                          }
                          size={15}
                        />
                        {fileName(file)}
                        <ArrowDownToLine size={13} />
                      </a>
                    ))}
                </div>
                {trash && (
                  <p className="field-hint">
                    {item.visibility?.record_deleted ? "任务记录已删除；" : ""}
                    {item.visibility?.results_deleted
                      ? "成果已删除"
                      : "成果保留中"}
                  </p>
                )}
                <ManageButton
                  job={item}
                  target={trash ? "both" : "results"}
                  restore={trash}
                  done={jobs.reload}
                />
                <Link to={"/app/jobs/" + item.id} className="result-link">
                  查看内容与详情
                  <ArrowRight size={16} />
                </Link>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <section className="panel">
          <Empty
            icon={FileCheck2}
            title={
              trash
                ? "回收站为空"
                : search
                  ? "没有找到匹配的成果"
                  : "你的教学成果将在这里积累"
            }
            description={
              search
                ? "试试其他课程名称。"
                : trash
                  ? "删除的成果和任务记录会出现在这里，可随时恢复。"
                  : "完成一次生成后，即可集中查看和下载文件。"
            }
            action={
              !search &&
              !trash && (
                <Link to="/app/create" className="button primary">
                  创建第一份材料
                  <ArrowRight size={16} />
                </Link>
              )
            }
          />
        </section>
      )}
    </>
  );
}

function SettingsPage() {
  const loaded = useLoad<Settings>("/workbench/settings"),
    { notify, refresh } = useContext(AppContext);
  const [form, setForm] = useState<(Settings & { api_key: string }) | null>(
      null,
    ),
    [showKey, setShowKey] = useState(false),
    [busy, setBusy] = useState(""),
    [connection, setConnection] = useState<{
      ok: boolean;
      message: string;
    } | null>(null),
    [catalog, setCatalog] = useState<string[]>([
      "deepseek-flash",
      "deepseek-v4-pro",
    ]);
  useEffect(() => {
    if (loaded.data) setForm({ ...loaded.data, api_key: "" });
  }, [loaded.data]);
  const update = (
    key: keyof (Settings & { api_key: string }),
    value: unknown,
  ) => {
    setForm((v) => (v ? { ...v, [key]: value } : v));
    setConnection(null);
  };
  if (loaded.error)
    return <ErrorBox text={loaded.error} retry={loaded.reload} />;
  if (!form) return <Spinner text="正在读取模型设置…" />;
  const save = async () => {
    await api("/workbench/settings", {
      method: "PUT",
      body: JSON.stringify(form),
    });
    setForm((v) => (v ? { ...v, api_key: "" } : v));
    refresh();
  };
  return (
    <>
      <PageHeader
        eyebrow="连接适合你的 AI 助手"
        title="模型设置"
        description="模型密钥保存在后端，生成时使用你选择的供应商和模型。"
      />
      <form
        className="settings-layout"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy("save");
          try {
            await save();
            notify("模型设置已保存，新任务将使用当前配置。");
            loaded.reload();
          } catch (err) {
            notify((err as Error).message, true);
          } finally {
            setBusy("");
          }
        }}
      >
        <div>
          <section className="panel form-panel">
            <div className="section-heading">
              <span className="section-icon">
                <Zap size={22} />
              </span>
              <div>
                <h2>模型连接</h2>
                <p>当前配置将用于后续创建的生成任务。</p>
              </div>
            </div>
            <label className="field">
              模型供应商
              <select
                value={form.provider}
                onChange={(e) => {
                  const provider = e.target.value;
                  setForm((v) =>
                    v
                      ? {
                          ...v,
                          provider,
                          model: v.models[provider] || "",
                          api_key: "",
                        }
                      : v,
                  );
                  setConnection(null);
                }}
              >
                {Object.entries(providerNames).map(([key, label]) => (
                  <option value={key} key={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              模型名称
              <input
                required
                maxLength={200}
                value={form.model}
                list={
                  form.provider === "deepseek" ? "model-catalog" : undefined
                }
                onChange={(e) => update("model", e.target.value)}
                placeholder="填写供应商支持的模型 ID"
              />
              <datalist id="model-catalog">
                {catalog.map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </datalist>
              <span className="field-hint">
                模型名称可以手动填写。
                {form.provider === "deepseek" && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={!!busy}
                    onClick={async () => {
                      setBusy("models");
                      try {
                        await save();
                        const data = await api<{ models: { id: string }[] }>(
                          "/settings/deepseek-models",
                        );
                        setCatalog(data.models.map((v) => v.id));
                        notify(`已读取 ${data.models.length} 个可用模型。`);
                      } catch (e) {
                        notify((e as Error).message, true);
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    保存并刷新可用模型
                    <RefreshCw size={12} />
                  </button>
                )}
              </span>
            </label>
            {form.provider !== "ollama" && (
              <label className="field">
                API Key <span className="optional">留空保留现有密钥</span>
                <div className="password-field">
                  <input
                    type={showKey ? "text" : "password"}
                    autoComplete="new-password"
                    value={form.api_key}
                    onChange={(e) => update("api_key", e.target.value)}
                    placeholder={
                      form.provider_keys[form.provider]
                        ? "已配置 · " + form.provider_keys[form.provider]
                        : "输入供应商提供的 API Key"
                    }
                  />
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={showKey ? "隐藏密钥" : "显示密钥"}
                    onClick={() => setShowKey(!showKey)}
                  >
                    {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </label>
            )}
            {form.provider === "deepseek" && (
              <>
                <label className="field">
                  API 地址
                  <input
                    type="url"
                    required
                    value={form.deepseek_base_url}
                    onChange={(e) =>
                      update("deepseek_base_url", e.target.value)
                    }
                  />
                </label>
                <div className="switch-field">
                  <div>
                    <strong>开启思考模式</strong>
                    <p>适用于复杂教学设计，会增加用量和等待时间。</p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={form.deepseek_thinking}
                    aria-label="开启思考模式"
                    className={`switch ${form.deepseek_thinking ? "on" : ""}`}
                    onClick={() =>
                      update("deepseek_thinking", !form.deepseek_thinking)
                    }
                  >
                    <span />
                  </button>
                </div>
                {form.deepseek_thinking && (
                  <div className="form-grid">
                    <label className="field">
                      推理强度
                      <select
                        value={form.deepseek_reasoning_effort}
                        onChange={(e) =>
                          update("deepseek_reasoning_effort", e.target.value)
                        }
                      >
                        <option value="low">轻量 · low</option>
                        <option value="high">标准 · high</option>
                        <option value="max">深入 · max</option>
                      </select>
                    </label>
                    <label className="field">
                      额外推理 Token 预算
                      <input
                        type="number"
                        min={0}
                        max={131072}
                        value={form.deepseek_reasoning_tokens}
                        onChange={(e) =>
                          update(
                            "deepseek_reasoning_tokens",
                            Number(e.target.value),
                          )
                        }
                      />
                    </label>
                  </div>
                )}
                <details className="advanced-settings">
                  <summary>
                    高级连接设置
                    <ChevronDown size={15} />
                  </summary>
                  <div className="form-grid">
                    <label className="field">
                      请求超时（秒）
                      <input
                        type="number"
                        min={10}
                        max={1800}
                        value={form.deepseek_timeout}
                        onChange={(e) =>
                          update("deepseek_timeout", Number(e.target.value))
                        }
                      />
                    </label>
                    <label className="field">
                      图片审核模型（可选）
                      <input
                        value={form.deepseek_vision_model}
                        onChange={(e) =>
                          update("deepseek_vision_model", e.target.value)
                        }
                        placeholder="默认使用所选模型"
                      />
                    </label>
                  </div>
                  <p className="field-hint">
                    选择仅支持文本的主模型时，可以明确指定具备视觉能力的图片审核模型。
                  </p>
                </details>
              </>
            )}
            {connection && (
              <div
                className={`notice ${connection.ok ? "success" : "error"}`}
                role="status"
              >
                {connection.ok ? (
                  <CheckCircle2 size={19} />
                ) : (
                  <CircleAlert size={19} />
                )}
                <span>{connection.message}</span>
              </div>
            )}
            <div className="settings-actions">
              <button
                type="button"
                className="button secondary"
                disabled={!!busy}
                onClick={async () => {
                  setBusy("connection");
                  setConnection(null);
                  try {
                    await save();
                    const r = await api<{
                      connected: boolean;
                      model: string;
                      error?: string;
                    }>("/workbench/connection", { method: "POST" });
                    setConnection({
                      ok: r.connected,
                      message: r.connected
                        ? `连接成功，${r.model} 可以使用。`
                        : friendlyError(r.error || "连接未成功，请检查配置。"),
                    });
                    loaded.reload();
                  } catch (e) {
                    setConnection({ ok: false, message: (e as Error).message });
                  } finally {
                    setBusy("");
                  }
                }}
              >
                {busy === "connection" ? (
                  <Loader2 size={17} className="spin" />
                ) : (
                  <Zap size={17} />
                )}
                保存并验证连接
              </button>
              <button className="button primary" disabled={!!busy}>
                {busy === "save" ? (
                  <Loader2 size={17} className="spin" />
                ) : (
                  <Check size={17} />
                )}
                保存设置
              </button>
            </div>
          </section>
          <section className="panel form-panel profile-panel">
            <h2>工作台称呼</h2>
            <p className="muted">用于欢迎语和工作台展示。</p>
            <label className="field">
              你的称呼
              <input
                value={form.teacher_name}
                maxLength={100}
                onChange={(e) => update("teacher_name", e.target.value)}
                placeholder=""
              />
            </label>
            <p className="field-hint">修改后点击上方“保存设置”一起保存。</p>
          </section>
        </div>
        <aside className="settings-aside">
          <div className="panel">
            <ShieldCheck className="blue-text" size={25} />
            <h3>你的模型，由你选择</h3>
            <p>API Key 不会写入前端代码，也不会在页面中返回完整内容。</p>
            <div className="aside-separator" />
            <h4>关于 DeepSeek</h4>
            <p>
              Flash 适合日常备课，支持图片输入；Pro
              可用于更复杂的内容设计。具体可用模型以你的账户为准。
            </p>
            <a
              className="text-button"
              href="https://platform.deepseek.com"
              target="_blank"
              rel="noreferrer"
            >
              前往 DeepSeek 平台 ↗
            </a>
            <div className="aside-separator" />
            <p className="small-label">
              连接验证会发送一条简短的真实模型请求，并保存当前配置。
            </p>
          </div>
        </aside>
      </form>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
