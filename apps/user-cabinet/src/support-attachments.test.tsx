import React,{useState} from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn, spyOn, restoreAllMocks} from "@vitest/spy";
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {AttachmentUpload,AttachmentFiles} from './support-attachments';
afterEach(()=>{cleanup();restoreAllMocks()});
it('reuses the upload key after an uncertain response',async(t)=>{
 t.mock.method(globalThis.crypto.subtle, 'digest', async () => new Uint8Array(32).buffer);
 t.mock.method(globalThis.crypto, 'randomUUID', () => 'upload-stable-key');
 let attempts=0;
 const request=fn(async(_p:string,_o?:RequestInit)=>{if(++attempts===1)throw Error('Ответ потерян');return {id:8,name:'log.txt',size:3,sha256:'00'.repeat(32)}});
 function Host(){const [value,setValue]=useState<any[]>([]);return <AttachmentUpload ticketId={4} request={request} value={value} onChange={setValue}/>}
 render(<Host/>);const input=screen.getByLabelText(/Вложения/);const file=new File(['abc'],'log.txt',{type:'text/plain'});
 fireEvent.change(input,{target:{files:[file]}});await screen.findByText('Ответ потерян');
 await waitFor(()=>expect((input as HTMLInputElement).disabled).to.equal(false));
 fireEvent.change(input,{target:{files:[file]}});await screen.findByText(/log.txt · 1 КБ/);
 expect(request.mock.calls).to.have.lengthOf(2);expect(request.mock.calls[0][0]).to.equal('/api/me/support/tickets/4/attachments');
 expect(request.mock.calls[0][1]!.headers).to.deep.equal(request.mock.calls[1][1]!.headers);
 expect(JSON.parse(String(request.mock.calls[1][1]!.body))).to.deep.equal({name:'log.txt',content_base64:'YWJj'});
});
it('downloads through the protected endpoint with no public media link',async()=>{
 const request=fn(async(_p:string)=>({name:'log.txt',content_base64:'YWJj'}));
 const create=fn((_blob:Blob)=> 'blob:private-file');Object.defineProperty(URL,'createObjectURL',{value:create,configurable:true});Object.defineProperty(URL,'revokeObjectURL',{value:fn(),configurable:true});
 const click=spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
 render(<AttachmentFiles files={[{id:8,name:'log.txt',size:3}]} request={request}/>);
 fireEvent.click(screen.getByRole('button',{name:'log.txt · 1 КБ'}));await waitFor(()=>expect(click.mock.calls).not.to.be.empty);
 expect(request.mock.calls).to.deep.include(['/api/me/support/attachments/8']);expect(create.mock.calls[0][0].type).to.equal('application/octet-stream');
});

it('recovers lost draft ids and allows removing excess files',async()=>{
 const request=fn(async(path:string,options?:RequestInit)=>options?.method==='DELETE'?{ok:true}:Array.from({length:4},(_,i)=>({id:i+1,name:`log${i+1}.txt`,size:3})));
 function Host(){const [value,setValue]=useState<any[]>([]);return <AttachmentUpload ticketId={4} request={request} value={value} onChange={setValue}/>}
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Восстановить загруженные файлы'}));
 await screen.findByText(/log4.txt/);expect(request.mock.calls).to.deep.include(['/api/me/support/tickets/4/attachments/drafts']);
 expect((screen.getByLabelText(/Вложения/) as HTMLInputElement).disabled).to.equal(true);
 fireEvent.click(screen.getAllByRole('button',{name:'Убрать из сообщения'})[0]);
 await waitFor(()=>expect(screen.queryByText(/log1.txt/)).to.be.null);
 expect(request.mock.calls).to.deep.include(['/api/me/support/attachments/1',{method:'DELETE'}]);
});
