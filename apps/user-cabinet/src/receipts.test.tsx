import React from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn} from "@vitest/spy";
import {cleanup,render,screen} from '@testing-library/react';
import {MyReceipts} from './receipts';
afterEach(cleanup);
it('lists receipts with a link to the tax service',async()=>{
 const request=fn().mockResolvedValue([{payment_id:1,kind:'income',amount:'1499.00',name:'Подписка VPN «Год» на 365 дн.',receipt_url:'https://lknpd.nalog.ru/api/v1/receipt/1/2/print',created_at:'2026-10-26T20:00:00Z'}]);
 render(<MyReceipts request={request}/>);
 expect((await screen.findByText('Открыть чек')).getAttribute('href')).to.equal('https://lknpd.nalog.ru/api/v1/receipt/1/2/print');
 expect(request.mock.calls).to.deep.include(['/api/me/receipts']);
});
it('shows nothing without receipts',async()=>{
 const {container}=render(<MyReceipts request={fn().mockResolvedValue([])}/>);
 await Promise.resolve();expect(container.textContent).to.equal('');
});
