/** 集中式 API 客户端：同源 `/api/v1`，统一错误归一化。页面组件不直接 fetch。 */

export interface AppError {
  code: string;
  message: string;      // 后端原文，用于日志
  userMessage: string;  // 界面展示
  retryable: boolean;
  status?: number;
  details?: Record<string, unknown>;
}

const BASE = "/api/v1";
const API_KEY_STORAGE = "travel_api_key";
const RETRYABLE_CODES = new Set(["LLM_FAILED", "LLM_INVALID_OUTPUT", "INTERNAL", "NETWORK", "TIMEOUT"]);

const USER_MESSAGES: Record<string, string> = {
  CARD_NOT_CONFIRMED: "需求卡还没有确认，请先确认需求卡再生成方案。",
  COMPLETENESS_TOO_LOW: "需求卡信息还不够完整，补齐必填项后才能确认。",
  CARD_NOT_READY: "需求卡仍有必问项未确认或冲突未解决，暂时不能生成。",
  CANDIDATES_TOO_FEW: "按当前条件筛出的酒店太少，暂不生成。请按建议放宽档次、预算或日期。",
  LLM_FAILED: "模型服务暂时不可用，请稍后重试。你输入的内容已保留。",
  LLM_INVALID_OUTPUT: "模型返回的结果不符合约定格式，已自动重试仍失败，请再试一次。",
  LLM_BUDGET_EXCEEDED: "今日演示 AI 额度已用完，请明天再试。",
  LLM_RATE_LIMITED: "演示请求较频繁，请一分钟后再试。",
  LLM_BUSY: "演示服务正在处理其他需求，请稍后再试。",
  LLM_INPUT_TOO_LARGE: "本次需求内容过长，请精简后再试。",
  CONV_NOT_FOUND: "找不到这个会话，可能链接已失效。",
  PLAN_NOT_FOUND: "找不到这个方案。",
  VERSION_NOT_FOUND: "方案还没有生成完成。",
  NETWORK: "网络连接失败，请检查后端服务是否在运行。",
  TIMEOUT: "请求超时，请重试。",
  INTERNAL: "服务内部错误，请稍后重试。",
  AUTH_REQUIRED: "请先登录后继续。",
  AUTH_INVALID: "登录凭证无效或已失效，请重新登录。",
  FORBIDDEN: "当前账号没有执行此操作的权限。",
  AUTH_CONFIG_INVALID: "服务端鉴权配置无效，请联系管理员。",
};

export function setApiKey(value: string): void {
  if (typeof window === "undefined") return;
  if (value) window.sessionStorage.setItem(API_KEY_STORAGE, value);
  else window.sessionStorage.removeItem(API_KEY_STORAGE);
}

export function getApiKey(): string {
  return typeof window === "undefined" ? "" : window.sessionStorage.getItem(API_KEY_STORAGE) ?? "";
}

export function isAppError(e: unknown): e is AppError {
  return typeof e === "object" && e !== null && "code" in e && "userMessage" in e;
}

export function normalizeError(status: number, body: unknown): AppError {
  const err = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null)?.error;
  const code = err?.code ?? (status >= 500 ? "INTERNAL" : "HTTP_" + status);
  const message = err?.message ?? `HTTP ${status}`;
  return {
    code,
    message,
    userMessage: USER_MESSAGES[code] ?? message,
    retryable: RETRYABLE_CODES.has(code) || status >= 500,
    status,
    details: err?.details,
  };
}

export function networkError(e: unknown): AppError {
  const timeout = e instanceof DOMException && e.name === "AbortError";
  const code = timeout ? "TIMEOUT" : "NETWORK";
  return { code, message: e instanceof Error ? e.message : String(e), userMessage: USER_MESSAGES[code], retryable: true };
}

export async function apiFetch<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), init.timeoutMs ?? 30_000);
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(getApiKey() ? { "X-API-Key": getApiKey() } : {}), ...(init.headers ?? {}) },
    });
  } catch (e) {
    clearTimeout(timer);
    throw networkError(e);
  }
  clearTimeout(timer);
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const error = normalizeError(res.status, body);
    if (res.status === 401 && typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.dispatchEvent(new Event("travel:auth-required"));
    }
    throw error;
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, data?: unknown) => apiFetch<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) }),
  patch: <T>(path: string, data: unknown) => apiFetch<T>(path, { method: "PATCH", body: JSON.stringify(data) }),
};
