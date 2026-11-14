import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {SubscriptionCommerce} from './subscription-commerce';
afterEach(()=>cleanup());
it('retains the quote and payment key after an uncertain purchase response',async()=>{
 let attempt=0;const current={plan_id:1,traffic_gb:100,devices:2,expires_at:'2026-12-01T00:00:00Z'};
 const request=vi.fn(async(p:string,o?:RequestInit)=>{
  if(p.endsWith('/commerce'))return {subscription_id:1,current,balance:'100.00',currency:'RUB',plans:[],packages:[{id:1,traffic_gb:50,price:'25.00'}]};
  if(p.endsWith('/quote'))return {id:'fixed-quote',amount:'25.00',currency:'RUB',expires_at:'2026-10-02T15:01:00Z',before:current,after:{...current,traffic_gb:150}};
  if(p.endsWith('/purchase')){if(++attempt===1)throw Error('Ответ потерян');return {id:9}}
  return [];
 });
 render(<SubscriptionCommerce request={request} reload={async()=>{}}/>);
 await screen.findByLabelText('Новые условия');fireEvent.change(screen.getByLabelText('Новые условия'),{target:{value:'traffic_addon:1'}});fireEvent.click(screen.getByRole('button',{name:'Рассчитать доплату'}));await screen.findByText('К оплате: 25.00 RUB');
 fireEvent.click(screen.getByRole('button',{name:'Подтвердить с кошелька'}));await screen.findByText('Ответ потерян');await waitFor(()=>expect((screen.getByRole('button',{name:'Подтвердить с кошелька'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'Подтвердить с кошелька'}));await screen.findByText('Заказ принят. Его статус показан ниже.');
 const calls=request.mock.calls.filter(([p])=>p.endsWith('/purchase'));expect(calls).toHaveLength(2);expect(calls[0][1]!.headers).toEqual(calls[1][1]!.headers);expect(JSON.parse(String(calls[1][1]!.body))).toEqual({quote_id:'fixed-quote'});
});
