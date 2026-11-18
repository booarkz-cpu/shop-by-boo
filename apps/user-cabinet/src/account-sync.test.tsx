import {waitFor} from "@testing-library/react";
import {it} from "node:test";
import {expect} from "chai";
import {fn} from "@vitest/spy";
import {watchAccount} from './account-sync';
const answer=(status:number,body?:object)=>({status,json:async()=>body} as unknown as Response);
it('reloads only when the version changes and keeps long-polling with since',async()=>{
 const calls:string[]=[];const replies=[answer(200,{version:'a'}),answer(304),answer(200,{version:'b'})];
 const fetcher=fn(async(url:string)=>{calls.push(url);const r=replies.shift();if(!r)return new Promise<Response>(()=>{});return r});
 const changed=fn();const stop=watchAccount('',changed,fetcher);
 await waitFor(()=>expect(changed.mock.calls).to.have.lengthOf(1));stop();
 expect(calls[0]).to.equal('/api/me/sync');expect(calls[1]).to.equal('/api/me/sync?since=a&wait=25');expect(calls[2]).to.equal('/api/me/sync?since=a&wait=25');
});
