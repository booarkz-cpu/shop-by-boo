import React,{useState} from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {AttachmentUpload,AttachmentFiles} from './support-attachments';
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});
it('reuses the upload key after an uncertain response',async()=>{
 vi.stubGlobal('crypto',{subtle:{digest:async()=>new Uint8Array(32).buffer},randomUUID:()=> 'upload-stable-key'});
 let attempts=0;
 const request=vi.fn(async(_p:string,_o?:RequestInit)=>{if(++attempts===1)throw Error('Ответ потерян');return {id:8,name:'log.txt',size:3,sha256:'00'.repeat(32)}});
 function Host(){const [value,setValue]=useState<any[]>([]);return <AttachmentUpload ticketId={4} request={request} value={value} onChange={setValue}/>}
 render(<Host/>);const input=screen.getByLabelText(/Вложения/);const file=new File(['abc'],'log.txt',{type:'text/plain'});
 fireEvent.change(input,{target:{files:[file]}});await screen.findByText('Ответ потерян');
 await waitFor(()=>expect((input as HTMLInputElement).disabled).toBe(false));
 fireEvent.change(input,{target:{files:[file]}});await screen.findByText(/log.txt · 1 КБ/);
 expect(request.mock.calls).toHaveLength(2);expect(request.mock.calls[0][0]).toBe('/api/me/support/tickets/4/attachments');
 expect(request.mock.calls[0][1]!.headers).toEqual(request.mock.calls[1][1]!.headers);
 expect(JSON.parse(String(request.mock.calls[1][1]!.body))).toEqual({name:'log.txt',content_base64:'YWJj'});
});
it('downloads through the protected endpoint with no public media link',async()=>{
 const request=vi.fn(async(_p:string)=>({name:'log.txt',content_base64:'YWJj'}));
 const create=vi.fn((_blob:Blob)=> 'blob:private-file');Object.defineProperty(URL,'createObjectURL',{value:create,configurable:true});Object.defineProperty(URL,'revokeObjectURL',{value:vi.fn(),configurable:true});
 const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
 render(<AttachmentFiles files={[{id:8,name:'log.txt',size:3}]} request={request}/>);
 fireEvent.click(screen.getByRole('button',{name:'log.txt · 1 КБ'}));await waitFor(()=>expect(click).toHaveBeenCalled());
 expect(request).toHaveBeenCalledWith('/api/me/support/attachments/8');expect(create.mock.calls[0][0].type).toBe('application/octet-stream');
});

it('recovers lost draft ids and allows removing excess files',async()=>{
 const request=vi.fn(async(path:string,options?:RequestInit)=>options?.method==='DELETE'?{ok:true}:Array.from({length:4},(_,i)=>({id:i+1,name:`log${i+1}.txt`,size:3})));
 function Host(){const [value,setValue]=useState<any[]>([]);return <AttachmentUpload ticketId={4} request={request} value={value} onChange={setValue}/>}
 render(<Host/>);fireEvent.click(screen.getByRole('button',{name:'Восстановить загруженные файлы'}));
 await screen.findByText(/log4.txt/);expect(request).toHaveBeenCalledWith('/api/me/support/tickets/4/attachments/drafts');
 expect((screen.getByLabelText(/Вложения/) as HTMLInputElement).disabled).toBe(true);
 fireEvent.click(screen.getAllByRole('button',{name:'Убрать из сообщения'})[0]);
 await waitFor(()=>expect(screen.queryByText(/log1.txt/)).toBeNull());
 expect(request).toHaveBeenCalledWith('/api/me/support/attachments/1',{method:'DELETE'});
});
