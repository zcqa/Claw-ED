export type Output = "teacher" | "student" | "slides";
export type Material = {
  id: string;
  name: string;
  kind: string;
  size: number;
  status: string;
  error: string;
  characters: number;
  created_at: string;
  text?: string;
};
export type Job = {
  visibility?: { record_deleted?: boolean; results_deleted?: boolean };
  id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  error: string | null;
  payload: {
    topic: string;
    subject: string;
    grade: string;
    outputs?: Output[];
    duration_minutes?: number;
    requirements?: string;
    content?: string;
    material_ids?: string[];
    reuse_task_id?: string;
    teacher_template_id?: string;
    student_template_id?: string;
    word_templates?: Record<string, { name: string; version: number }>;
  };
  result: {
    files?: string[];
    title?: string;
    objective?: string;
    text?: string;
    warnings?: string[];
    errors?: string[];
    model?: string;
    required_outputs?: Record<string, string>;
  } | null;
  events?: { phase: string; message: string; created_at: string }[];
  content?: Record<string, unknown>;
  materials?: { id: string; name: string }[];
};
export type Overview = {
  auth_required: boolean;
  provider: string;
  model: string;
  has_key: boolean;
  worker_online: boolean;
  materials: number;
  jobs: number;
  completed: number;
  active: number;
  files: number;
  teacher_name: string;
};
export type Settings = {
  provider: string;
  model: string;
  models: Record<string, string>;
  provider_keys: Record<string, string>;
  has_key: boolean;
  key_masked: string;
  teacher_name: string;
  deepseek_base_url: string;
  deepseek_thinking: boolean;
  deepseek_reasoning_effort: string;
  deepseek_reasoning_tokens: number;
  deepseek_timeout: number;
  deepseek_vision_model: string;
};

export const outputNames: Record<Output, string> = {
  teacher: "教师教案",
  student: "学生讲义",
  slides: "教学课件",
};
export const providerNames: Record<string, string> = {
  deepseek: "DeepSeek",
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google Gemini",
  ollama: "Ollama",
  openrouter: "OpenRouter",
};
export const statusNames: Record<string, string> = {
  queued: "等待处理",
  running: "生成中",
  done: "已完成",
  failed: "需要处理",
  interrupted: "已中断",
  cancel_requested: "正在取消",
  cancelled: "已取消",
};
export function fileName(path: string) {
  return path.split(/[\\/]/).pop() || "生成文件";
}
export function dateTime(value: string, full = false) {
  return new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    ...(full ? { year: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
export function sizeText(bytes: number) {
  return bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
export function friendlyError(message: string) {
  const known: Record<string, string> = {
    "Missing auth token": "请先登录教学工作台。",
    "Invalid auth token": "登录已过期，请重新输入访问令牌。",
    "Failed to fetch": "无法连接服务，请确认 8005 端口的服务正在运行。",
    "Job is missing or cannot transition from its current status":
      "任务状态已变化，请刷新后重试。",
  };
  if (known[message]) return known[message];
  if (
    message.includes("No DeepSeek API key") ||
    message.includes("API key missing")
  )
    return "尚未配置 DeepSeek API Key，请前往模型设置。";
  if (message.includes("401") || message.includes("API key is invalid"))
    return "模型 API Key 无效，请检查模型设置。";
  if (message.includes("402")) return "模型账户余额不足，请检查供应商账户。";
  if (message.includes("429")) return "模型服务请求较多，请稍后恢复任务。";
  if (message.toLowerCase().includes("timed out"))
    return "请求超时，请稍后重试或增加模型请求超时。";
  return message;
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error(friendlyError("Failed to fetch"));
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("服务返回异常，请刷新页面后重试。");
  }
  if (!response.ok) {
    if (response.status === 401 && path !== "/workbench/session")
      window.dispatchEvent(new Event("auth-required"));
    const detail = data.detail || data.error;
    throw new Error(
      friendlyError(
        typeof detail === "string"
          ? detail
          : response.status === 422
            ? "请检查表单内容，部分字段格式不正确。"
            : "操作未完成，请稍后重试。",
      ),
    );
  }
  return data as T;
}
