export const API_BASE = ((import.meta as any).env?.VITE_API_BASE_URL as string) || "";

export interface RequestOptions {
  method?: string;
  body?: any;
  token?: string | null;
  includeAuth?: boolean;
}

export async function requestJson(
  apiBase: string,
  path: string,
  { method = "GET", body, token, includeAuth = true }: RequestOptions = {}
): Promise<any> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (includeAuth && token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${apiBase}${path}`, {
    method,
    headers,
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const ct = res.headers.get("content-type") || "";
  const payload = ct.includes("application/json") ? await res.json() : await res.text();

  if (!res.ok) {
    const detail =
      typeof payload === "string"
        ? payload
        : payload.detail || payload.message || "Yêu cầu không thành công.";
    const err = new Error(detail) as any;
    err.status = res.status;
    throw err;
  }
  return payload;
}
