/**
 * Reading API answers for the admin panel, the personal cabinet and the Mini App (v28.58.0, BUG-H1/H2).
 *
 * Before, both `req()` helpers did `let d = {}; try { d = await r.json() } catch {}` and threw only
 * when `!r.ok`. A successful answer that was not JSON — most often the `index.html` that nginx
 * serves for any unknown path when `/api` is not routed to the backend — silently became `{}`.
 * Screens then crashed far from the cause: `(s || []).map is not a function` (an object is truthy)
 * and `Cannot read properties of undefined (reading 'trim')`. Now such an answer is an error with
 * a message that names the request, so the screen shows it instead of crashing.
 */
export class ApiFormatError extends Error {
  status: number;
  constructor(path: string, status: number, contentType: string) {
    const what = /html/i.test(contentType) ? "HTML-страницу" : "ответ не в формате JSON";
    super(`Сервер вернул ${what} на запрос ${path} (HTTP ${status}). Проверьте, что адрес API указывает на backend.`);
    this.name = "ApiFormatError";
    this.status = status;
  }
}

/** The JSON body of an API answer. An empty body is `{}`; a non-JSON body of a 2xx answer is an error.
 *  For an error status a non-JSON body is `{}`, so the caller reports the HTTP status as before. */
export async function readJsonBody(r: Response, path: string): Promise<any> {
  if (r.status === 204 || r.status === 205) return {};
  const text = await r.text();
  if (!text.trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    if (!r.ok) return {};
    throw new ApiFormatError(path, r.status, r.headers.get("content-type") || "");
  }
}
