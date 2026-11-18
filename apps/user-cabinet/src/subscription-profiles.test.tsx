import React from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn} from "@vitest/spy";
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {SubscriptionProfiles} from './subscription-profiles';
afterEach(cleanup);
it('binds profile selection and rename to the visible profile id',async()=>{
 const request=fn(async(_p:string,_o?:RequestInit)=>({})),reload=fn(async()=>{});
 render(<SubscriptionProfiles profiles={[{id:4,name:'Телефон',plan:'Тариф',status:'active',is_primary:false}]} request={request} reload={reload}/>);
 fireEvent.click(screen.getByRole('button',{name:'Выбрать подписку'}));
 await waitFor(()=>expect(reload.mock.calls).to.have.lengthOf(1));
 expect(request.mock.calls[0][0]).to.equal('/api/me/subscriptions/4/select');
 fireEvent.change(screen.getByLabelText('Название подписки №4'),{target:{value:' Планшет '}});
 fireEvent.click(screen.getByRole('button',{name:'Сохранить название'}));
 await waitFor(()=>expect(reload.mock.calls).to.have.lengthOf(2));
 expect(request.mock.calls[1][0]).to.equal('/api/me/subscriptions/4');
 expect(JSON.parse(String(request.mock.calls[1][1]!.body))).to.deep.equal({name:'Планшет'});
});
