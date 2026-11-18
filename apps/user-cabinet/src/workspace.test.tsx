import React from "react";
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn, restoreAllMocks} from "@vitest/spy";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {Workspace} from "./workspace";
afterEach(()=>{cleanup();restoreAllMocks()});
const base={reload:async()=>{},plans:[{id:3,name:"Месяц",price:100}],provider:"yookassa",providers:["yookassa","rollypay","platega"],currency:"RUB",api:""};
it("sends a top-up with only configured agents and an idempotency key",async()=>{
 const request=fn(async(p:string,o?:RequestInit)=>p.endsWith("history")?{balance:"75.00",items:[]}:{});
 render(<Workspace {...base} kind="wallet" request={request}/>);await screen.findByText("75.00 RUB");
 expect(screen.getAllByRole("option").map(x=>x.textContent)).to.deep.equal(["YooKassa","RollyPay","Platega"]);
 fireEvent.change(screen.getByLabelText("Сумма пополнения"),{target:{value:"600"}});fireEvent.click(screen.getByRole("button",{name:"Пополнить"}));
 await waitFor(()=>expect(request.mock.calls).to.satisfy((calls: unknown[][]) => calls.some(args => args.length === 2 && args[0] === "/api/me/wallet/topup" && (args[1] as RequestInit)?.method === "POST")));
 const options=request.mock.calls.find(([p])=>p==="/api/me/wallet/topup")![1]!;
 expect(JSON.parse(String(options.body))).to.deep.equal({amount:600,provider:"yookassa"});expect((options.headers as any)["Idempotency-Key"]).to.match(/^[a-f0-9-]{36}$/);
});
it("keeps the gift purchase key after an uncertain result",async()=>{
 const request=fn(async(p:string,o?:RequestInit)=>{if(p.endsWith("purchase"))throw Error("Результат не определён");return []});
 render(<Workspace {...base} kind="gifts" request={request}/>);await screen.findByText("Подарить подписку");
 fireEvent.change(screen.getByLabelText("Тариф"),{target:{value:"3"}});fireEvent.click(screen.getByRole("button",{name:"Купить в подарок"}));await screen.findByRole("alert");
 await waitFor(()=>expect((screen.getByRole("button",{name:"Купить в подарок"}) as HTMLButtonElement).disabled).to.equal(false));fireEvent.click(screen.getByRole("button",{name:"Купить в подарок"}));
 await waitFor(()=>expect(request.mock.calls.filter(([p])=>p.endsWith("purchase"))).to.have.lengthOf(2));const calls=request.mock.calls.filter(([p])=>p.endsWith("purchase"));expect((calls[0][1]!.headers as any)["Idempotency-Key"]).to.deep.equal((calls[1][1]!.headers as any)["Idempotency-Key"]);
});
it("preserves the support draft if delivery fails",async()=>{
 const request=fn(async(p:string,o?:RequestInit)=>{if(o?.method==="POST")throw Error("Нет соединения");return []});render(<Workspace {...base} kind="support" request={request}/>);await screen.findByText("Новое обращение");
 fireEvent.change(screen.getByLabelText("Тема"),{target:{value:"Помощь с VPN"}});fireEvent.change(screen.getByLabelText("Сообщение"),{target:{value:"Не подключается"}});fireEvent.click(screen.getByRole("button",{name:"Отправить"}));await screen.findByRole("alert");
 expect((screen.getByLabelText("Тема") as HTMLInputElement).value).to.equal("Помощь с VPN");expect((screen.getByLabelText("Сообщение") as HTMLInputElement).value).to.equal("Не подключается");
});
it("marks a notification and updates its state",async()=>{
 let read=false;const request=fn(async(p:string,o?:RequestInit)=>{if(p.endsWith("/read")){read=true;return {ok:true}}return [{id:9,title:"Ответ",body:"Проверьте настройки",read,created_at:"2026-10-01T10:00:00Z"}]});render(<Workspace {...base} kind="notifications" request={request}/>);await screen.findByText("Ответ");fireEvent.click(screen.getByRole("button",{name:"Прочитано"}));await waitFor(()=>expect(screen.queryByRole("button",{name:"Прочитано"})).to.be.null);expect(request.mock.calls).to.satisfy((calls: unknown[][]) => calls.some(args => args.length === 2 && args[0] === "/api/me/notifications/9/read" && (args[1] as RequestInit)?.method === "POST"));
});
it("distinguishes payment confirmation from pending VPN fulfillment",async()=>{
 const request=fn(async()=>({payments:[{id:1,amount:"100.00",currency:"RUB",status:"paid",fulfillment_status:"pending",created_at:"2026-10-01T10:00:00Z"}]}));render(<Workspace {...base} kind="payments" request={request}/>);await screen.findByText("Оплачен");expect(screen.getByText("Ожидает выдачи")).to.be.ok;expect((screen.getByRole("link",{name:/Квитанция/}) as HTMLAnchorElement).getAttribute("href")).to.equal("/api/me/payments/1/invoice");
});
it("opens a support conversation and retries the same follow-up safely",async()=>{
 let attempt=0;const request=fn(async(p:string,o?:RequestInit)=>{
  if(p.endsWith("/messages")&&o?.method==="POST"){if(++attempt===1)throw Error("Связь потеряна");return {created:true}}
  if(p.endsWith("/messages"))return {status:attempt>1?"open":"resolved",messages:[{id:0,role:"customer",body:"Вопрос",created_at:"2026-10-02T10:00:00Z"},{id:1,role:"admin",body:"Первый ответ",created_at:"2026-10-02T10:01:00Z"}],next_cursor:null};
  return [{id:4,subject:"VPN",message:"Вопрос",status:"resolved",admin_reply:"Первый ответ"}]
 });
 render(<Workspace {...base} kind="support" request={request}/>);await screen.findByText("Открыть переписку");fireEvent.click(screen.getByRole("button",{name:"Открыть переписку"}));await screen.findByText("Ответ получен");
 const input=screen.getByLabelText("Ответ в обращение #4");fireEvent.change(input,{target:{value:"Нужна ещё помощь"}});fireEvent.click(screen.getByRole("button",{name:"Отправить сообщение"}));await screen.findByText("Связь потеряна");
 expect((input as HTMLTextAreaElement).value).to.equal("Нужна ещё помощь");await waitFor(()=>expect((screen.getByRole("button",{name:"Отправить сообщение"}) as HTMLButtonElement).disabled).to.equal(false));fireEvent.click(screen.getByRole("button",{name:"Отправить сообщение"}));await screen.findByText("Ожидает ответа поддержки");
 const calls=request.mock.calls.filter(([p,o])=>p.endsWith("messages")&&o?.method==="POST");expect(calls).to.have.lengthOf(2);expect((calls[0][1]!.headers as any)["Idempotency-Key"]).to.equal((calls[1][1]!.headers as any)["Idempotency-Key"]);expect(JSON.parse(String(calls[1][1]!.body))).to.deep.equal({message:"Нужна ещё помощь",attachment_ids:[]});expect((screen.getByLabelText("Ответ в обращение #4") as HTMLTextAreaElement).value).to.equal("");
});
