import {expect,it,vi} from 'vitest';
import {watchAccount} from './account-sync';
const answer=(status:number,body?:object)=>({status,json:async()=>body} as unknown as Response);
it('reloads only when the version changes and keeps long-polling with since',async()=>{
 const calls:string[]=[];const replies=[answer(200,{version:'a'}),answer(304),answer(200,{version:'b'})];
 const fetcher=vi.fn(async(url:string)=>{calls.push(url);const r=replies.shift();if(!r)return new Promise<Response>(()=>{});return r});
 const changed=vi.fn();const stop=watchAccount('',changed,fetcher);
 await vi.waitFor(()=>expect(changed).toHaveBeenCalledTimes(1));stop();
 expect(calls[0]).toBe('/api/me/sync');expect(calls[1]).toBe('/api/me/sync?since=a&wait=25');expect(calls[2]).toBe('/api/me/sync?since=a&wait=25');
});
