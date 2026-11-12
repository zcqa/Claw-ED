import { useEffect, useRef, useState } from "react";
import { DocumentTemplateEditor } from "./document-template";
import { api, dateTime } from "./api";
import {
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  Upload,
  Trash2,
  Undo2,
} from "lucide-react";

export type TemplateField = {
  id: string;
  key: string;
  label: string;
  instruction: string;
  kind: "text" | "rows" | "blocks";
  purpose: string;
  anchors: string[];
  retained: string[];
  rationale: string;
  slots: { id: string; anchors: string[] }[];
  uncertain: string;
  confirmed: boolean;
  columns: { key: string; label: string }[];
  action: string;
  value: string;
  anchor: string;
  prefix: string;
};
export type TemplateSpec = {
  name: string;
  role: "teacher" | "student";
  instruction: string;
  fields: TemplateField[];
  auto_grow: boolean;
  engine?: string;
  understanding: {
    purpose?: string;
    audience?: string;
    organization?: string;
    relations?: string[];
  };
  sections: {
    id: string;
    label: string;
    purpose: string;
    field_ids: string[];
  }[];
  coverage?: { complete: boolean; pending: string[] };
};
export type Block = {
  formula_count?: number;
  media_count?: number;
  id: string;
  anchor: string;
  kind: string;
  text: string;
  label: string;
  part: string;
};
export type WordTemplate = {
  id: string;
  name: string;
  role: "teacher" | "student";
  mode: string;
  status: string;
  version: number;
  spec: TemplateSpec;
  warnings: string[];
  error: string;
  needs_upgrade?: boolean;
  analysis?: { phase: string; message: string };
  created_at: string;
  blocks?: Block[];
};
const statusNames: Record<string, string> = {
  uploaded: "待提取",
  analyzing: "正在理解全文",
  review: "待确认",
  ready: "可使用",
};

export function TemplateSelect({
  role,
  value,
  onChange,
  templates,
  original = false,
}: {
  role: "teacher" | "student";
  value: string;
  onChange: (value: string) => void;
  templates: WordTemplate[];
  original?: boolean;
}) {
  return (
    <label className="field">
      {role === "teacher" ? "教师教案" : "学生讲义"}格式
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {original && <option value="__original__">沿用原任务的模板版本</option>}
        <option value="">默认格式</option>
        {templates
          .filter(
            (t) => t.role === role && t.status === "ready" && !t.needs_upgrade,
          )
          .map((t) => (
            <option value={t.id} key={t.id}>
              {t.name} · 第 {t.version} 版
            </option>
          ))}
      </select>
      {!!value &&
        value !== "__original__" &&
        !templates.some(
          (t) =>
            t.id === value &&
            t.status === "ready" &&
            !t.needs_upgrade &&
            t.role === role,
        ) && (
          <span className="danger-text">该模板当前不可用，请重新选择。</span>
        )}
    </label>
  );
}

export function TemplateLibrary({
  notify,
  initialId = "",
}: {
  notify: (text: string, error?: boolean) => void;
  initialId?: string;
}) {
  const [items, setItems] = useState<WordTemplate[]>([]),
    [current, setCurrent] = useState<WordTemplate | null>(null);
  const [trash, setTrash] = useState(false);
  const requestSerial = useRef(0);
  const [spec, setSpec] = useState<TemplateSpec | null>(null);
  const [busy, setBusy] = useState(false),
    [dirty, setDirty] = useState(false),
    [error, setError] = useState("");
  const [role, setRole] = useState("teacher"),
    [mode, setMode] = useState("auto"),
    [removed, setRemoved] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const refresh = async () => {
    const serial = ++requestSerial.current;
    try {
      const values = await api<WordTemplate[]>(
        "/workbench/templates" + (trash ? "?trash=true" : ""),
      );
      if (serial !== requestSerial.current) return;
      setItems(values);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    void refresh();
  }, [trash]);
  const changeView = (value: boolean) => {
    if (value === trash) return;
    if (dirty) {
      notify("请先保存或放弃当前修改。", true);
      return;
    }
    setCurrent(null);
    setSpec(null);
    setItems([]);
    setTrash(value);
  };
  const manageTemplate = async (item: WordTemplate, deleted: boolean) => {
    if (dirty) {
      notify("请先保存或放弃当前修改。", true);
      return;
    }
    setBusy(true);
    try {
      await api(`/workbench/templates/${item.id}/visibility`, {
        method: "POST",
        body: JSON.stringify({ deleted }),
      });
      if (current?.id === item.id) {
        setCurrent(null);
        setSpec(null);
      }
      setRemoved(deleted ? item.id : "");
      await refresh();
      notify(
        deleted
          ? "模板已移至回收站，历史任务仍使用已保存的版本。"
          : "模板已恢复。",
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const open = async (id: string) => {
    if (dirty) {
      notify("请先保存当前模板，或点击放弃修改。", true);
      return;
    }
    try {
      const item = await api<WordTemplate>("/workbench/templates/" + id);
      setCurrent(item);
      setSpec(item.spec);
      setDirty(false);
    } catch (e) {
      notify((e as Error).message, true);
    }
  };
  useEffect(() => {
    if (initialId) void open(initialId);
  }, [initialId]);
  useEffect(() => {
    if (current?.status !== "analyzing") return;
    const timer = window.setInterval(async () => {
      try {
        const item = await api<WordTemplate>(
          "/workbench/templates/" + current.id,
        );
        setCurrent(item);
        if (item.status !== "analyzing") {
          setSpec(item.spec);
          setDirty(false);
          void refresh();
          notify(
            item.error || "全文理解与模板归纳已完成，请检查后保存。",
            !!item.error,
          );
        }
      } catch (e) {
        setError((e as Error).message);
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [current?.id, current?.status]);
  const analyzing = current?.status === "analyzing";
  const covered = new Map<string, number>();
  spec?.fields.forEach((f) =>
    (f.anchors || []).forEach((a) => covered.set(a, (covered.get(a) || 0) + 1)),
  );
  const coverageValid =
    !!current?.blocks?.length &&
    current.blocks.every((b) => covered.get(b.anchor) === 1) &&
    covered.size === current.blocks.length;
  const update = (change: Partial<TemplateSpec>) => {
    setSpec((v) => (v ? { ...v, ...change } : v));
    setDirty(true);
  };
  const upload = async (file?: File) => {
    if (!file) return;
    if (dirty) {
      notify("请先保存或放弃当前修改。", true);
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("role", role);
    form.append("mode", mode);
    setBusy(true);
    try {
      const item = await api<WordTemplate>("/workbench/templates", {
        method: "POST",
        body: form,
      });
      await refresh();
      await open(item.id);
      notify(
        item.mode === "sample"
          ? "样例已上传，请提取模板后检查栏目。"
          : "已读取占位符，请先理解全文并提取其用途。",
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  const analyze = async () => {
    if (!current) return;
    if (dirty) {
      notify("请先保存或放弃当前修改。", true);
      return;
    }
    setBusy(true);
    try {
      await api(`/workbench/templates/${current.id}/analyze`, {
        method: "POST",
      });
      await open(current.id);
      await refresh();
      notify(
        "已开始理解全文，完成后会显示结构和规则。你可以离开此页，稍后回来查看。",
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    if (!current || !spec) return;
    setBusy(true);
    try {
      const item = await api<WordTemplate>(
        `/workbench/templates/${current.id}`,
        {
          method: "PUT",
          body: JSON.stringify({ spec, version: current.version }),
        },
      );
      const detail = await api<WordTemplate>(`/workbench/templates/${item.id}`);
      setCurrent(detail);
      setSpec(detail.spec);
      setDirty(false);
      await refresh();
      notify("模板已保存并启用，可以下载空白预览或在创建任务时选择。");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="panel-heading template-page-heading">
        <div>
          <h1>Word 模板</h1>
          <p>模板决定内容结构；首次确认后可反复用于不同课程。</p>
        </div>
      </div>
      <div className="button-row library-tabs">
        <button
          className={`button ${!trash ? "primary" : "secondary"}`}
          disabled={busy}
          onClick={() => changeView(false)}
        >
          我的模板
        </button>
        <button
          className={`button ${trash ? "primary" : "secondary"}`}
          disabled={busy}
          onClick={() => changeView(true)}
        >
          <Trash2 size={17} />
          回收站
        </button>
      </div>
      {!trash && (
        <section className="panel template-upload">
          <label className="field">
            适用材料
            <select
              value={role}
              disabled={busy}
              onChange={(e) => setRole(e.target.value)}
            >
              <option value="teacher">教师教案</option>
              <option value="student">学生讲义</option>
            </select>
          </label>
          <label className="field">
            文件类型
            <select
              value={mode}
              disabled={busy}
              onChange={(e) => setMode(e.target.value)}
            >
              <option value="auto">自动识别</option>
              <option value="placeholder">模式 A：带占位符的模板</option>
              <option value="sample">模式 B：普通教案样例</option>
            </select>
          </label>
          <button
            className="button primary"
            disabled={busy}
            onClick={() => input.current?.click()}
          >
            {busy ? (
              <Loader2 size={18} className="spin" />
            ) : (
              <Upload size={18} />
            )}
            上传 Word 模板
          </button>
          <input
            ref={input}
            className="sr-only"
            type="file"
            accept=".docx"
            aria-label="选择 Word 模板文件"
            onChange={(e) => void upload(e.target.files?.[0])}
          />
        </section>
      )}
      {error && <p className="error-box">{error}</p>}
      {!!removed && (
        <div className="notice soft">
          模板已移至回收站，历史任务仍使用已保存的版本。
          <button
            className="text-button"
            onClick={async () => {
              try {
                await api(`/workbench/templates/${removed}/visibility`, {
                  method: "POST",
                  body: JSON.stringify({ deleted: false }),
                });
                setRemoved("");
                await refresh();
              } catch (e) {
                notify((e as Error).message, true);
              }
            }}
          >
            撤销删除
          </button>
        </div>
      )}
      <div className="template-workspace">
        <aside className="panel template-list">
          <div className="panel-heading">
            <h2>{trash ? "已删除模板" : "我的模板"}</h2>
            <button
              className="icon-button"
              aria-label="刷新模板列表"
              onClick={() => void refresh()}
            >
              <RefreshCw size={16} />
            </button>
          </div>
          {!items.length && (
            <p className="muted">
              {trash ? "回收站为空。" : "上传学校模板或已有教案，开始提取。"}
            </p>
          )}
          {items.map((item) => (
            <div className="template-list-row" key={item.id}>
              <button
                className={`template-list-item ${current?.id === item.id ? "selected" : ""}`}
                disabled={busy || trash}
                onClick={() => void open(item.id)}
              >
                <FileText size={18} />
                <span>
                  <strong>{item.name}</strong>
                  <small>
                    {item.role === "teacher" ? "教案" : "讲义"} ·{" "}
                    {item.mode === "placeholder" ? "占位符" : "样例提取"} ·{" "}
                    {item.needs_upgrade && item.status === "ready"
                      ? "待升级"
                      : statusNames[item.status] || item.status}
                  </small>
                  <small>
                    {item.version ? `第 ${item.version} 版 · ` : ""}
                    {dateTime(item.created_at)}
                  </small>
                </span>
              </button>
              <button
                className={`icon-button ${trash ? "" : "danger-text"}`}
                disabled={busy || item.status === "analyzing"}
                aria-label={`${trash ? "恢复" : "删除"}${item.name}`}
                title={
                  item.status === "analyzing"
                    ? "提取完成后可删除"
                    : trash
                      ? "恢复模板"
                      : "删除模板"
                }
                onClick={() => void manageTemplate(item, !trash)}
              >
                {trash ? <Undo2 size={18} /> : <Trash2 size={18} />}
              </button>
            </div>
          ))}
        </aside>
        {trash ? (
          <section className="panel template-editor">
            <h2>模板回收站</h2>
            <p>点击左侧恢复按钮，可将模板放回“我的模板”。</p>
            <p>
              删除后不再用于新任务；历史任务引用的模板版本和生成文件继续保留。
            </p>
          </section>
        ) : current && spec ? (
          <section className="panel template-editor">
            <div className="panel-heading">
              <div>
                <h2>提取与确认</h2>
                <p>
                  {current.mode === "placeholder"
                    ? "检查占位符的用途和填写要求。"
                    : "检查文档功能、组织规则与原文依据。"}
                </p>
              </div>
              <span
                className={`badge ${current.status === "ready" ? "done" : "running"}`}
              >
                {dirty ? "有未保存修改" : statusNames[current.status]}
              </span>
            </div>
            <div className="form-grid">
              <label className="field">
                模板名称
                <input
                  value={spec.name}
                  maxLength={150}
                  disabled={busy || analyzing}
                  onChange={(e) => update({ name: e.target.value })}
                />
              </label>
              <label className="field">
                适用材料
                <select
                  value={spec.role}
                  disabled={busy || analyzing}
                  onChange={(e) =>
                    update({ role: e.target.value as "teacher" | "student" })
                  }
                >
                  <option value="teacher">教师教案</option>
                  <option value="student">学生讲义</option>
                </select>
              </label>
            </div>
            <label className="field">
              整体内容组织要求
              <textarea
                rows={3}
                maxLength={6000}
                value={spec.instruction}
                disabled={busy || analyzing}
                onChange={(e) => update({ instruction: e.target.value })}
              />
            </label>
            <div className="button-row">
              {(current.mode === "sample" ||
                current.spec.engine === "pending-v2" ||
                current.spec.engine === "document-v2") && (
                <button
                  className="button secondary"
                  disabled={busy || analyzing}
                  onClick={() => void analyze()}
                >
                  {busy ? (
                    <Loader2 className="spin" size={16} />
                  ) : (
                    <RefreshCw size={16} />
                  )}
                  {spec.engine === "document-v2"
                    ? "重新理解并提取"
                    : "理解全文并提取模板"}
                </button>
              )}
              <a
                className="button secondary"
                href={`/api/workbench/templates/${current.id}/file`}
              >
                下载原文件
              </a>
              {current.status === "ready" && !dirty && (
                <a
                  className="button secondary"
                  href={`/api/workbench/templates/${current.id}/file?preview=true`}
                >
                  下载空白模板预览
                </a>
              )}
              <button
                className="text-button danger-text"
                disabled={busy || dirty || analyzing}
                onClick={() => void manageTemplate(current, true)}
              >
                删除模板
              </button>
            </div>
            {busy && (
              <p className="notice soft">
                正在处理，请稍候。智能提取会调用当前模型分析样例的栏目与组织规则。
              </p>
            )}
            {current.warnings?.map((w) => (
              <p className="notice warning" key={w}>
                {w}
              </p>
            ))}
            {analyzing && (
              <p className="notice soft" role="status">
                <Loader2 size={18} className="spin" />{" "}
                {current.analysis?.message || "正在理解文档"}。完成后自动更新。
              </p>
            )}
            {current.error && (
              <p className="error-box">
                {current.error} 可重新提取；之前已保存的任务版本仍然有效。
              </p>
            )}
            {spec.engine === "document-v2" ? (
              <DocumentTemplateEditor
                item={current}
                spec={spec}
                onChange={update}
                disabled={busy || !!analyzing}
              />
            ) : (
              <p className="notice warning">
                {current.needs_upgrade
                  ? "这是旧版按位置提取的模板，请重新理解全文后升级。历史任务仍使用原版本。"
                  : "请先理解全文并提取模板，再检查各部分的功能、组织规则和原文范围。"}
              </p>
            )}
            <label className="check-row">
              <input
                type="checkbox"
                checked={spec.auto_grow}
                disabled={busy || analyzing}
                onChange={(e) => update({ auto_grow: e.target.checked })}
              />
              允许固定高度的表格行随内容增高，避免长内容遮挡
            </label>
            <div className="form-actions">
              <button
                className="button secondary"
                disabled={busy || !dirty}
                onClick={() => {
                  setSpec(current.spec);
                  setDirty(false);
                }}
              >
                放弃修改
              </button>
              <button
                className="button primary"
                disabled={
                  busy ||
                  analyzing ||
                  spec.engine !== "document-v2" ||
                  !coverageValid ||
                  !spec.fields.length ||
                  spec.fields.some((f) => f.uncertain && !f.confirmed)
                }
                onClick={() => void save()}
              >
                {busy ? (
                  <Loader2 className="spin" size={17} />
                ) : (
                  <Plus size={17} />
                )}
                保存并启用模板
              </button>
            </div>
          </section>
        ) : (
          <section className="panel template-editor">
            <h2>为学校保存一份可重复使用的模板</h2>
            <p>
              模式 A 支持带占位符的 Word；模式 B
              从普通教案样例中提取栏目、填写区域与教学组织规则。
            </p>
            <p>
              模板用于规定结构和格式，不会加入课程资料正文。没有选择模板时，仍使用默认格式。
            </p>
          </section>
        )}
      </div>
    </>
  );
}
