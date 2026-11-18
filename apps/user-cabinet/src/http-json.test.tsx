import {rejects} from "node:assert/strict";
import {it} from "node:test";
import {expect} from "chai";
import {ApiFormatError, readJsonBody} from "./http-json";

const answer = (status: number, body: string, type = "application/json") =>
  new Response(status === 204 ? null : body, {status, headers: {"content-type": type}});

it("BUG-H1/H2: the SPA index.html on a 200 answer is an error, not an empty object", async () => {
  const html = '<!DOCTYPE html><html><head></head><body><div id="root"></div></body></html>';
  // The old helper turned this into {}: `(d.items || []).map` then threw «map is not a function»
  // for objects, and `d.name.trim()` threw «reading 'trim'».
  await rejects(readJsonBody(answer(200, html, "text/html"), "/api/admin/plans"), ApiFormatError);
  await rejects(readJsonBody(answer(200, html, "text/html"), "/api/admin/plans"), /HTML-страницу на запрос \/api\/admin\/plans \(HTTP 200\)/);
  await rejects(readJsonBody(answer(200, "not json", "text/plain"), "/api/me"), /не в формате JSON/);
});

it("keeps JSON, empty and error answers as before", async () => {
  expect(await readJsonBody(answer(200, '[{"id":1}]'), "/x")).to.deep.equal([{id: 1}]);
  expect(await readJsonBody(answer(200, '{"name":"Люси"}'), "/x")).to.deep.equal({name: "Люси"});
  expect(await readJsonBody(answer(204, ""), "/x")).to.deep.equal({});
  expect(await readJsonBody(answer(200, "  "), "/x")).to.deep.equal({});
  // An error status with an HTML body (a 502 page of the proxy) gives {}, so the caller reports HTTP 502.
  expect(await readJsonBody(answer(502, "<html>Bad Gateway</html>", "text/html"), "/x")).to.deep.equal({});
  expect(await readJsonBody(answer(400, '{"detail":"Неверный код"}'), "/x")).to.deep.equal({detail: "Неверный код"});
});
