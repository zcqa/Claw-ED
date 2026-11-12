import { useState } from "react";
import type { TemplateField, TemplateSpec, WordTemplate } from "./templates";

export function DocumentTemplateEditor({
  item,
  spec,
  onChange,
  disabled,
}: {
  item: WordTemplate;
  spec: TemplateSpec;
  onChange: (v: Partial<TemplateSpec>) => void;
  disabled: boolean;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [splitAt, setSplitAt] = useState("");
  const blocks = item.blocks || [];
  const counts = new Map<string, number>();
  spec.fields.forEach((f) =>
    (f.anchors || []).forEach((a) => counts.set(a, (counts.get(a) || 0) + 1)),
  );
  const missing = blocks.filter((b) => !counts.has(b.anchor));
  const overlaps = [...counts.values()].filter((n) => n > 1).length;
  const pending = spec.fields.filter((f) => f.uncertain && !f.confirmed);
  const fieldUpdate = (id: string, v: Partial<TemplateField>) =>
    onChange({
      fields: spec.fields.map((f) => (f.id === id ? { ...f, ...v } : f)),
    });
  const current =
    spec.fields.find((f) => f.id === selected[selected.length - 1]) ||
    spec.fields[0];
  const members = current
    ? blocks.filter((b) => current.anchors?.includes(b.anchor))
    : [];
  const merge = () => {
    const chosen = spec.fields.filter((f) => selected.includes(f.id));
    if (
      chosen.length < 2 ||
      chosen.some((f) => f.kind !== "blocks" || f.action !== chosen[0].action)
    )
      return;
    const anchors = blocks
      .filter((b) => chosen.some((f) => f.anchors.includes(b.anchor)))
      .map((b) => b.anchor);
    const positions = anchors.map((a) =>
      blocks.findIndex((b) => b.anchor === a),
    );
    if (
      Math.max(...positions) - Math.min(...positions) + 1 !==
      positions.length
    ) {
      window.alert("请合并原文中连续的部分。");
      return;
    }
    const first = chosen[0];
    if (
      chosen.map((f) => f.instruction).join("\n").length > 2000 ||
      ["purpose", "rationale", "uncertain"].some(
        (k) =>
          chosen.map((f) => String(f[k as keyof TemplateField])).join("\n")
            .length > 4000,
      )
    ) {
      window.alert(
        "合并后的规则过长，请先整理相关部分的功能和填写规则，避免丢失内容。",
      );
      return;
    }
    const merged = {
      ...first,
      label: chosen
        .map((f) => f.label)
        .join(" / ")
        .slice(0, 150),
      purpose: [...new Set(chosen.map((f) => f.purpose))].join("\n"),
      instruction: [...new Set(chosen.map((f) => f.instruction))].join("\n"),
      anchors,
      retained: chosen.flatMap((f) => f.retained || []),
      slots: [],
      rationale: [...new Set(chosen.map((f) => f.rationale))].join("\n"),
      uncertain: chosen
        .map((f) => f.uncertain)
        .filter(Boolean)
        .join("\n"),
      confirmed: chosen.every((f) => !f.uncertain || f.confirmed),
    };
    onChange({
      fields: spec.fields.flatMap((f) =>
        f.id === first.id ? [merged] : selected.includes(f.id) ? [] : [f],
      ),
      sections: spec.sections
        .map((s) => ({
          ...s,
          field_ids: s.field_ids.filter(
            (id) => !selected.includes(id) || id === first.id,
          ),
        }))
        .filter((s) => s.field_ids.length),
    });
    setSelected([first.id]);
  };
  const split = () => {
    if (!current || !splitAt) return;
    const i = current.anchors.indexOf(splitAt);
    if (i <= 0) return;
    const id =
      "f" + (Math.max(...spec.fields.map((f) => Number(f.id.slice(1)))) + 1);
    const left = current.anchors.slice(0, i),
      right = current.anchors.slice(i);
    const second = {
      ...current,
      id,
      key: "content_" + id,
      label: current.label + "（后半部分）",
      anchors: right,
      retained: current.retained.filter((a) => right.includes(a)),
      slots: [],
    };
    onChange({
      fields: spec.fields.flatMap((f) =>
        f.id === current.id
          ? [
              {
                ...current,
                anchors: left,
                retained: current.retained.filter((a) => left.includes(a)),
                slots: [],
              },
              second,
            ]
          : [f],
      ),
      sections: spec.sections.map((s) => ({
        ...s,
        field_ids: s.field_ids.flatMap((x) =>
          x === current.id ? [x, id] : [x],
        ),
      })),
    });
    setSplitAt("");
  };
  const understanding = spec.understanding || {};
  return (
    <fieldset className="semantic-editor" disabled={disabled}>
      <div className="coverage-strip" role="status">
        <strong>
          全文覆盖 {blocks.length - missing.length} / {blocks.length}
        </strong>
        <span>{spec.fields.length} 个逻辑部分</span>
        <span>
          {blocks.reduce((n, b) => n + (b.formula_count || 0), 0)} 处公式
        </span>
        <span>
          {overlaps} 处重叠 · {pending.length} 项待确认
        </span>
      </div>
      {(!!missing.length || !!overlaps) && (
        <p className="error-box">
          全文范围不完整，请重新提取或调整范围后保存。遗漏位置：
          {missing.map((b) => b.id).join("、") || "无"}。
        </p>
      )}
      <details open className="understanding-card">
        <summary>系统对这份文档的理解</summary>
        {(
          [
            ["purpose", "文档用途"],
            ["audience", "面向读者"],
            ["organization", "组织方式"],
          ] as const
        ).map(([k, label]) => (
          <label className="field" key={k}>
            {label}
            <textarea
              rows={2}
              value={String(understanding[k] || "")}
              onChange={(e) =>
                onChange({
                  understanding: { ...understanding, [k]: e.target.value },
                })
              }
            />
          </label>
        ))}
        <label className="field">
          部分之间的关系（每行一条）
          <textarea
            rows={3}
            value={(understanding.relations || []).join("\n")}
            onChange={(e) =>
              onChange({
                understanding: {
                  ...understanding,
                  relations: e.target.value.split("\n"),
                },
              })
            }
          />
        </label>
      </details>
      <p className="field-hint">
        名称、功能和层级来自当前文件。选中连续部分可合并，也可以展开原文范围后拆分。段落和单元格只是原文位置，生成时按逻辑部分整体组织内容。
      </p>
      {item.mode === "placeholder" && (
        <p className="notice soft">
          作者设置的占位符决定填入边界；这里根据全文解释各占位符用途，原有循环与版式保持有效。
        </p>
      )}
      {item.mode === "sample" && (
        <div className="button-row">
          <button
            className="button secondary"
            type="button"
            disabled={selected.length < 2}
            onClick={merge}
          >
            合并选中的连续部分
          </button>
          <span className="muted">合并部分须使用相同填写方式</span>
        </div>
      )}
      <div className="semantic-grid">
        <div className="semantic-outline">
          {spec.sections.map((s) => (
            <section key={s.id}>
              <h3>{s.label}</h3>
              {s.field_ids.map((id) => {
                const f = spec.fields.find((x) => x.id === id);
                return (
                  f && (
                    <label
                      key={id}
                      className={`semantic-part ${selected.includes(id) ? "selected" : ""}`}
                    >
                      <input
                        type="checkbox"
                        checked={selected.includes(id)}
                        onChange={(e) => {
                          setSelected(
                            e.target.checked
                              ? [...selected, id]
                              : selected.filter((x) => x !== id),
                          );
                          setSplitAt("");
                        }}
                      />
                      <span>
                        <strong>{f.label}</strong>
                        <small>{f.purpose}</small>
                        <small>
                          {f.kind === "blocks"
                            ? `${f.anchors.length} 个原文位置 · `
                            : ""}
                          {
                            (
                              {
                                generate: "按新课程生成",
                                preserve: "保留原文",
                                blank: "留空",
                                manual: "人工填写",
                                fixed: "固定文字",
                              } as Record<string, string>
                            )[f.action]
                          }
                          {f.uncertain && !f.confirmed ? " · 待确认" : ""}
                        </small>
                      </span>
                    </label>
                  )
                );
              })}
            </section>
          ))}
        </div>
        <div className="semantic-detail">
          {current ? (
            <>
              <label className="field">
                部分名称
                <input
                  value={current.label}
                  maxLength={150}
                  onChange={(e) =>
                    fieldUpdate(current.id, { label: e.target.value })
                  }
                />
              </label>
              <label className="field">
                在这份文档中的功能
                <textarea
                  rows={3}
                  value={current.purpose}
                  maxLength={4000}
                  onChange={(e) =>
                    fieldUpdate(current.id, { purpose: e.target.value })
                  }
                />
              </label>
              <label className="field">
                填写方式
                <select
                  value={current.action}
                  onChange={(e) =>
                    fieldUpdate(current.id, {
                      action: e.target.value,
                      retained:
                        e.target.value === "preserve"
                          ? [...current.anchors]
                          : current.action === "preserve"
                            ? []
                            : current.retained,
                    })
                  }
                >
                  {Object.entries({
                    generate: "按新课程生成",
                    ...(current.kind === "blocks"
                      ? { preserve: "保留原文" }
                      : {}),
                    blank: "留空",
                    manual: "人工填写",
                    fixed: "固定文字",
                  })
                    .filter(
                      ([k]) =>
                        current.kind !== "rows" ||
                        ["generate", "blank"].includes(k),
                    )
                    .map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                </select>
              </label>
              <label className="field">
                新内容的组织与填写规则
                <textarea
                  rows={7}
                  value={current.instruction}
                  maxLength={2000}
                  onChange={(e) =>
                    fieldUpdate(current.id, { instruction: e.target.value })
                  }
                />
              </label>
              <label className="field">
                提取判断与保留依据
                <textarea
                  rows={3}
                  value={current.rationale}
                  maxLength={4000}
                  onChange={(e) =>
                    fieldUpdate(current.id, { rationale: e.target.value })
                  }
                />
              </label>
              {["manual", "fixed"].includes(current.action) && (
                <label className="field">
                  填写内容（未填写则留空）
                  <textarea
                    rows={3}
                    value={current.value}
                    onChange={(e) =>
                      fieldUpdate(current.id, { value: e.target.value })
                    }
                  />
                </label>
              )}
              {!!current.uncertain && (
                <div className="notice warning">
                  <p>{current.uncertain}</p>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={current.confirmed}
                      onChange={(e) =>
                        fieldUpdate(current.id, { confirmed: e.target.checked })
                      }
                    />
                    我已核对原文，确认当前处理方式
                  </label>
                </div>
              )}
              {current.kind === "blocks" && (
                <details>
                  <summary>
                    原文依据与填入范围（{members.length} 个位置）
                  </summary>
                  <p className="field-hint">
                    勾选仅保留可复用的固定标签。未勾选位置整体替换，不会默认遗留旧正文。
                  </p>
                  {members.map((b, i) => (
                    <div className="source-evidence" key={b.id}>
                      <label className="check-row">
                        <input
                          type="checkbox"
                          checked={current.retained.includes(b.anchor)}
                          disabled={current.action === "preserve"}
                          onChange={(e) =>
                            fieldUpdate(current.id, {
                              retained: e.target.checked
                                ? [...current.retained, b.anchor]
                                : current.retained.filter(
                                    (a) => a !== b.anchor,
                                  ),
                            })
                          }
                        />
                        {b.id} · {b.kind === "cell" ? "表格单元格" : "段落"} ·
                        保留此原文
                      </label>
                      <pre>{b.text || "（空白）"}</pre>
                      {i > 0 && (
                        <label className="check-row">
                          <input
                            type="radio"
                            name="split"
                            checked={splitAt === b.anchor}
                            onChange={() => setSplitAt(b.anchor)}
                          />
                          从这里拆为新的逻辑部分
                        </label>
                      )}
                    </div>
                  ))}
                  <button
                    type="button"
                    className="button secondary"
                    disabled={!splitAt}
                    onClick={split}
                  >
                    按所选位置拆分
                  </button>
                </details>
              )}
            </>
          ) : (
            <p className="muted">
              选择左侧逻辑部分，查看功能、生成规则及原文依据。
            </p>
          )}
        </div>
      </div>
    </fieldset>
  );
}
