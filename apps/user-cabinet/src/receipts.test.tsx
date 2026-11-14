import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {MyReceipts} from './receipts';
afterEach(cleanup);
it('lists receipts with a link to the tax service',async()=>{
 const request=vi.fn().mockResolvedValue([{payment_id:1,kind:'income',amount:'1499.00',name:'Подписка VPN «Год» на 365 дн.',receipt_url:'https://lknpd.nalog.ru/api/v1/receipt/1/2/print',created_at:'2026-10-26T20:00:00Z'}]);
 render(<MyReceipts request={request}/>);
 expect((await screen.findByText('Открыть чек')).getAttribute('href')).toBe('https://lknpd.nalog.ru/api/v1/receipt/1/2/print');
 expect(request).toHaveBeenCalledWith('/api/me/receipts');
});
it('shows nothing without receipts',async()=>{
 const {container}=render(<MyReceipts request={vi.fn().mockResolvedValue([])}/>);
 await Promise.resolve();expect(container.textContent).toBe('');
});
