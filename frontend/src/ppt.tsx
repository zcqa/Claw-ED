import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, dateTime } from "./api";
import {
  Loader2,
  Presentation,
  RefreshCw,
  Trash2,
  Undo2,
  Upload,
} from "lucide-react";

type Notify = (message: string, error?: boolean) => void;
type PptLimits = { max_pages: number; max_file_mb: number };
export type PptTemplate = {
  id: string;
  name: string;
  version: number;
  status: string;
  error: string;
  deleted: boolean;
  updated_at: string;
  progress: { message?: string; completed?: number; total?: number };
  spec: {
    page_count: number;
    instruction?: string;
    selected: string[];
    layouts: { id: string }[];
    upload?: { slide_image_urls: string[] };
  };
};

export function PptSelect({
  value,
  onChange,
  templates,
  original = false,
}: {
  value: string;
  onChange: (value: string) => void;
  templates: PptTemplate[];
  original?: boolean;
}) {
  return (
    <label>
      PPT 模板
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {original && <option value="__original__">沿用原任务的模板版本</option>}
        <option value="">系统默认 · 课堂清晰版</option>
        {templates
          .filter((t) => t.status === "ready")
          .map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} · 第 {t.version} 版
            </option>
          ))}
      </select>
    </label>
  );
}

export function PptTemplateLibrary({ notify }: { notify: Notify }) {
  const [items, setItems] = useState<PptTemplate[]>([]),
    [trash, setTrash] = useState(false);
  const [limits, setLimits] = useState<PptLimits | null>(null);
  const [detail, setDetail] = useState<PptTemplate | null>(null),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(""),
    [name, setName] = useState(""),
    [instruction, setInstruction] = useState("");
  const [selected, setSelected] = useState<string[]>([]),
    [removed, setRemoved] = useState<string | null>(null);
  const choose = async (id: string) => {
    try {
      const t = await api<PptTemplate>(`/workbench/ppt/templates/${id}`);
      setDetail(t);
      setName(t.name);
      setInstruction(t.spec.instruction || "");
      setSelected(t.spec.selected || []);
    } catch (e) {
      notify((e as Error).message, true);
    }
  };
  const load = useCallback(async () => {
    try {
      const [templates, currentLimits] = await Promise.all([
        api<PptTemplate[]>(
          "/workbench/ppt/templates" + (trash ? "?trash=true" : ""),
        ),
        api<PptLimits>("/workbench/ppt/limits"),
      ]);
      setItems(templates);
      setLimits(currentLimits);
      setError("");
      if (detail?.status === "analyzing") {
        const t = await api<PptTemplate>(
          `/workbench/ppt/templates/${detail.id}`,
        );
        setDetail(t);
        if (t.status !== "analyzing") setSelected(t.spec.selected || []);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [trash, detail?.id, detail?.status]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 4000);
    return () => clearInterval(timer);
  }, [load]);
  const analyze = async (t: PptTemplate) => {
    setBusy(true);
    try {
      await api(`/workbench/ppt/templates/${t.id}/analyze`, { method: "POST" });
      await choose(t.id);
      await load();
      notify("正在理解课件并提取版式，可在此查看进度。");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const manage = async (id: string, deleted: boolean) => {
    setBusy(true);
    try {
      await api(`/workbench/ppt/templates/${id}/visibility`, {
        method: "POST",
        body: JSON.stringify({ deleted }),
      });
      if (detail?.id === id) setDetail(null);
      setRemoved(deleted ? id : null);
      await load();
      notify(
        deleted ? "PPT 模板已移至回收站。历史课件保留。" : "PPT 模板已恢复。",
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="page-header">
        <div>
          <h1>PPT 模板</h1>
          <p>从已有课件提取版式与内容组织规则，选择需要复用的页面后保存。</p>
          <p className="muted">
            {limits
              ? `支持 1–${limits.max_pages} 页、${limits.max_file_mb} MB 以内的课件。范围内完整处理，不自动裁页。`
              : "正在读取上传限制…"}
          </p>
        </div>
      </div>
      <div className="button-row library-tabs">
        <button
          className={`button ${!trash ? "primary" : "secondary"}`}
          onClick={() => {
            setTrash(false);
            setDetail(null);
          }}
        >
          我的模板
        </button>
        <button
          className={`button ${trash ? "primary" : "secondary"}`}
          onClick={() => {
            setTrash(true);
            setDetail(null);
          }}
        >
          回收站
        </button>
        <button className="button secondary" onClick={() => void load()}>
          <RefreshCw size={17} />
          刷新
        </button>
        {!trash && (
          <label className="button primary">
            <Upload size={18} />
            上传 PPT 模板
            <input
              type="file"
              accept=".pptx"
              hidden
              disabled={busy || !limits}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                if (!limits) return;
                if (file.size > limits.max_file_mb * 1024 * 1024) {
                  notify(`PPT 模板不能超过 ${limits.max_file_mb} MB。`, true);
                  e.target.value = "";
                  return;
                }
                setBusy(true);
                try {
                  const form = new FormData();
                  form.append("file", file);
                  const t = await api<PptTemplate>("/workbench/ppt/templates", {
                    method: "POST",
                    body: form,
                  });
                  await choose(t.id);
                  await load();
                  setBusy(false);
                  await analyze(t);
                } catch (err) {
                  notify((err as Error).message, true);
                  setBusy(false);
                }
                e.target.value = "";
              }}
            />
          </label>
        )}
      </div>
      {removed && (
        <div className="notice soft">
          模板已删除，可从回收站恢复。
          <button
            className="text-button"
            onClick={() => void manage(removed, false)}
          >
            撤销删除
          </button>
        </div>
      )}
      {error && <div className="notice warning">{error}</div>}
      <div className="ppt-library-layout">
        <section className="panel ppt-template-list">
          {!items.length && (
            <p className="muted">
              {trash
                ? "回收站为空。"
                : "尚未上传 PPT 模板。未选择模板时使用系统默认版式。"}
            </p>
          )}
          {items.map((t) => (
            <div className="ppt-template-row" key={t.id}>
              <button
                className={`ppt-template-choice ${detail?.id === t.id ? "selected" : ""}`}
                onClick={() => void choose(t.id)}
              >
                <Presentation size={21} />
                <span>
                  <strong>{t.name}</strong>
                  <small>
                    {t.status === "analyzing"
                      ? "正在提取"
                      : t.status === "ready"
                        ? `可用 · 第 ${t.version} 版`
                        : t.status === "review"
                          ? "待确认"
                          : "待提取"}{" "}
                    · {t.spec.page_count} 页
                  </small>
                </span>
              </button>
              <button
                className="icon-button"
                aria-label={`${trash ? "恢复" : "删除"}${t.name}`}
                disabled={busy || t.status === "analyzing"}
                onClick={() => void manage(t.id, !trash)}
              >
                {trash ? <Undo2 size={17} /> : <Trash2 size={17} />}
              </button>
            </div>
          ))}
        </section>
        <section className="panel ppt-template-editor">
          {!detail ? (
            <div className="empty-state">
              <Presentation size={40} />
              <h2>{trash ? "恢复模板后继续使用" : "选择或上传一份课件"}</h2>
              <p>支持横版 PPTX。系统理解实际页面，不要求预先设置占位符。</p>
              <p className="muted">
                可选取课件中需要复用的代表页面制作模板；超过限制会在上传时明确提示。
              </p>
            </div>
          ) : (
            <>
              <div className="section-heading">
                <div>
                  <h2>{detail.name}</h2>
                  <p>{dateTime(detail.updated_at)} · 原文件保留</p>
                  <p>
                    原文件 {detail.spec.page_count} 页 · 已生成预览{" "}
                    {detail.spec.upload?.slide_image_urls.length || 0} 页 ·
                    已提取 {detail.spec.layouts.length} 页
                  </p>
                </div>
                <a
                  className="button secondary"
                  href={`/api/workbench/ppt/templates/${detail.id}/source`}
                >
                  下载原文件
                </a>
              </div>
              {detail.error && (
                <div className="notice warning">{detail.error}</div>
              )}
              {detail.status === "analyzing" ? (
                <div className="notice soft">
                  <Loader2 className="spin" size={20} />
                  {detail.progress.message || "正在等待课件引擎"}{" "}
                  {detail.progress.total
                    ? `${detail.progress.completed || 0}/${detail.progress.total} 页`
                    : ""}
                </div>
              ) : (
                <>
                  {!trash && (
                    <>
                      <label>
                        模板名称
                        <input
                          value={name}
                          maxLength={160}
                          onChange={(e) => setName(e.target.value)}
                        />
                      </label>
                      <label>
                        模板组织与使用要求
                        <textarea
                          rows={4}
                          value={instruction}
                          maxLength={5000}
                          onChange={(e) => setInstruction(e.target.value)}
                        />
                      </label>
                      <div className="button-row">
                        <button
                          className="button secondary"
                          disabled={busy}
                          onClick={() => void analyze(detail)}
                        >
                          重新理解并提取
                        </button>
                        {!!detail.spec.layouts?.length && (
                          <button
                            className="button primary"
                            disabled={busy || !selected.length}
                            onClick={async () => {
                              setBusy(true);
                              try {
                                await api(
                                  `/workbench/ppt/templates/${detail.id}`,
                                  {
                                    method: "PUT",
                                    body: JSON.stringify({
                                      version: detail.version,
                                      name,
                                      instruction,
                                      selected,
                                    }),
                                  },
                                );
                                await choose(detail.id);
                                await load();
                                notify("模板已保存，创建课程时可以选择使用。");
                              } catch (e) {
                                notify((e as Error).message, true);
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            确认并保存模板
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </>
              )}
              {!!detail.spec.layouts?.length && (
                <>
                  <h3>生成时可选用的页面版式</h3>
                  <p className="muted">
                    保留适合新课程的页面。生成时会按课程内容选择版式，不会逐页照搬原课件。
                  </p>
                  <div className="ppt-layout-grid">
                    {detail.spec.layouts.map((layout, i) => (
                      <label className="ppt-layout-card" key={layout.id}>
                        <img
                          loading="lazy"
                          src={`/api/workbench/ppt/templates/${detail.id}/preview/${i}`}
                          alt={`原课件第 ${i + 1} 页`}
                        />
                        <span>
                          <input
                            type="checkbox"
                            checked={selected.includes(layout.id)}
                            disabled={
                              trash || busy || detail.status === "analyzing"
                            }
                            onChange={(e) =>
                              setSelected((v) =>
                                e.target.checked
                                  ? [...v, layout.id]
                                  : v.filter((id) => id !== layout.id),
                              )
                            }
                          />
                          第 {i + 1} 页版式
                        </span>
                      </label>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}

type DeckView = {
  available: boolean;
  legacy?: boolean;
  message?: string;
  phase?: string;
  total?: number;
  completed?: number;
  template_name?: string;
  slides?: {
    index: number;
    chapter_title?: string;
    title: string;
    notes: string;
    content: Record<string, unknown>;
  }[];
};

export function PptViewer({
  taskId,
  notify,
  active = false,
}: {
  taskId: string;
  notify: Notify;
  active?: boolean;
}) {
  const navigate = useNavigate();
  const [deck, setDeck] = useState<DeckView | null>(null),
    [index, setIndex] = useState(0),
    [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [imageError, setImageError] = useState(false),
    [revision, setRevision] = useState(0);
  const load = useCallback(async () => {
    try {
      setDeck(await api<DeckView>(`/workbench/ppt/jobs/${taskId}`));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [taskId]);
  useEffect(() => {
    void load();
    if (!active) return;
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [load, active]);
  const slide = deck?.slides?.[index];
  return (
    <section className="panel ppt-viewer">
      <div className="section-heading">
        <div>
          <h2>课件预览与修改</h2>
          <p>
            {deck?.template_name || "教学课件"}
            {deck?.total ? ` · ${deck.total} 页` : ""}
          </p>
        </div>
        <button
          className="button secondary"
          onClick={() => {
            void load();
            setImageError(false);
            setRevision((v) => v + 1);
          }}
        >
          <RefreshCw size={17} />
          刷新预览
        </button>
      </div>
      {error && <div className="notice warning">{error}</div>}
      {!deck?.available ? (
        <p className="muted">
          {active
            ? deck?.phase === "editing"
              ? "正在修改所选页面，原课件保留。完成后可查看新课件。"
              : `正在编排并生成课件，已完成 ${deck?.completed || 0}/${deck?.total || "待编排"} 页。生成完成后可逐页预览。`
            : deck?.message || "暂无可预览课件，可恢复任务继续生成。"}
        </p>
      ) : (
        <>
          {deck.phase === "review" && (
            <div className="notice warning">
              有页面超出画布，请精简对应页内容后生成新课件。已生成的 Word 保留。
            </div>
          )}
          <div className="ppt-preview-layout">
            <nav className="ppt-page-list" aria-label="课件页面">
              {deck.slides?.map((s, i) => (
                <button
                  key={s.index}
                  className={index === i ? "selected" : ""}
                  onClick={() => {
                    setIndex(i);
                    setImageError(false);
                    setPrompt("");
                  }}
                >
                  <img
                    loading="lazy"
                    src={`/api/workbench/ppt/jobs/${taskId}/preview/${s.index}`}
                    alt=""
                  />
                  <span>
                    {i + 1}. {s.title}
                  </span>
                </button>
              ))}
            </nav>
            <div className="ppt-slide-detail">
              {slide && (
                <>
                  <h3>
                    第 {index + 1} 页 · {slide.title}
                  </h3>
                  {slide.chapter_title && <p className="muted">所属章节：{slide.chapter_title}</p>}
                  {imageError ? (
                    <div className="notice warning">
                      页面预览暂未完成，可刷新重试，或下载 PPTX 查看。
                    </div>
                  ) : (
                    <img
                      className="ppt-main-preview"
                      src={`/api/workbench/ppt/jobs/${taskId}/preview/${slide.index}?v=${revision}`}
                      alt={`第 ${index + 1} 页课件`}
                      onError={() => setImageError(true)}
                    />
                  )}
                  <details>
                    <summary>教师备注</summary>
                    <div className="pre-wrap">
                      {slide.notes.replace(/<\/?latex>/g, "") ||
                        "本页暂无教师备注。"}
                    </div>
                  </details>
                  {!active && (
                    <div className="ppt-edit-form">
                      <label>
                        修改这一页
                        <textarea
                          rows={3}
                          value={prompt}
                          maxLength={3000}
                          onChange={(e) => setPrompt(e.target.value)}
                        />
                      </label>
                      <p className="muted">
                        可修改文字与教师备注，保留原页版式。修改后生成新课件，原任务和原课件保留。
                      </p>
                      <button
                        className="button primary"
                        disabled={busy || !prompt.trim()}
                        onClick={async () => {
                          setBusy(true);
                          try {
                            const r = await api<{ id: string }>(
                              `/workbench/ppt/jobs/${taskId}/edit`,
                              {
                                method: "POST",
                                body: JSON.stringify({
                                  index: slide.index,
                                  prompt,
                                }),
                              },
                            );
                            notify("已创建单页修改任务，完成后可查看新课件。");
                            navigate("/app/jobs/" + r.id);
                          } catch (e) {
                            notify((e as Error).message, true);
                          } finally {
                            setBusy(false);
                          }
                        }}
                      >
                        {busy ? "正在提交…" : "修改并生成新课件"}
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </>
      )}
      {deck?.legacy && (
        <Link className="text-button" to={`/app/jobs/${taskId}`}>
          在任务中重新导出新版课件
        </Link>
      )}
    </section>
  );
}
