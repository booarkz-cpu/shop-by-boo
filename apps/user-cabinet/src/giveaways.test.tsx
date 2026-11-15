import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {GiveawayCard,Giveaways} from './giveaways';
afterEach(cleanup);
const row={id:1,title:'Prize wheel',description:'Free',kind:'wheel',phase:'open',entry_count:0,max_entries:10,winners_count:1,ends_at:'2027-01-01T00:00:00Z',prizes:[{amount:'0',weight:3},{amount:'5',weight:1}],currency:'RUB',my_entry:null};
it('shows odds and sends no client-controlled prize',async()=>{
 const request=vi.fn().mockResolvedValue({...row,my_entry:{outcome:'won',reward_amount:'5'}}),done=vi.fn();
 render(<GiveawayCard row={row} request={request} onDone={done}/>);
 expect(screen.getByText(/75.00%/)).toBeTruthy();fireEvent.click(screen.getByText('Получить результат колеса'));
 await waitFor(()=>expect(done).toHaveBeenCalledTimes(1));expect(request).toHaveBeenCalledWith('/api/me/giveaways/1/enter',{method:'POST'});
});
it('does not offer a second entry and shows a saved reward',()=>{
 render(<GiveawayCard row={{...row,my_entry:{outcome:'won',reward_amount:'5'}}} request={vi.fn()} onDone={vi.fn()}/>);
 expect(screen.queryByText('Получить результат колеса')).toBeNull();expect(screen.getByRole('status').textContent).toContain('начислено 5 RUB');
});
it('a network failure leaves a retry available without claiming a win',async()=>{
 const request=vi.fn().mockRejectedValue(new Error('Connection lost'));render(<GiveawayCard row={row} request={request} onDone={vi.fn()}/>);
 fireEvent.click(screen.getByText('Получить результат колеса'));await screen.findByRole('alert');expect(screen.queryByText('Вы выиграли')).toBeNull();expect(screen.getByText('Получить результат колеса').hasAttribute('disabled')).toBe(false);
});
it('keeps previous campaigns when loading a next page',async()=>{
 const request=vi.fn().mockResolvedValueOnce({items:[row],next_after:1}).mockResolvedValueOnce({items:[{...row,id:2,title:'Next'}],next_after:null});
 render(<Giveaways request={request} reload={vi.fn()}/>);await screen.findByText('Prize wheel');fireEvent.click(screen.getByText('Показать ещё'));await screen.findByText('Next');expect(screen.getByText('Prize wheel')).toBeTruthy();
});
