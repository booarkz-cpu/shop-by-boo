import React from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn} from "@vitest/spy";
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {GiveawayCard,Giveaways} from './giveaways';
afterEach(cleanup);
const row={id:1,title:'Prize wheel',description:'Free',kind:'wheel',phase:'open',entry_count:0,max_entries:10,winners_count:1,ends_at:'2027-01-01T00:00:00Z',prizes:[{amount:'0',weight:3},{amount:'5',weight:1}],currency:'RUB',my_entry:null};
it('shows odds and sends no client-controlled prize',async()=>{
 const request=fn().mockResolvedValue({...row,my_entry:{outcome:'won',reward_amount:'5'}}),done=fn();
 render(<GiveawayCard row={row} request={request} onDone={done}/>);
 expect(screen.getByText(/75.00%/)).to.be.ok;fireEvent.click(screen.getByText('Получить результат колеса'));
 await waitFor(()=>expect(done.mock.calls).to.have.lengthOf(1));expect(request.mock.calls).to.deep.include(['/api/me/giveaways/1/enter',{method:'POST'}]);
});
it('does not offer a second entry and shows a saved reward',()=>{
 render(<GiveawayCard row={{...row,my_entry:{outcome:'won',reward_amount:'5'}}} request={fn()} onDone={fn()}/>);
 expect(screen.queryByText('Получить результат колеса')).to.be.null;expect(screen.getByRole('status').textContent).to.include('начислено 5 RUB');
});
it('a network failure leaves a retry available without claiming a win',async()=>{
 const request=fn().mockRejectedValue(new Error('Connection lost'));render(<GiveawayCard row={row} request={request} onDone={fn()}/>);
 fireEvent.click(screen.getByText('Получить результат колеса'));await screen.findByRole('alert');expect(screen.queryByText('Вы выиграли')).to.be.null;expect(screen.getByText('Получить результат колеса').hasAttribute('disabled')).to.equal(false);
});
it('keeps previous campaigns when loading a next page',async()=>{
 const request=fn().mockResolvedValueOnce({items:[row],next_after:1}).mockResolvedValueOnce({items:[{...row,id:2,title:'Next'}],next_after:null});
 render(<Giveaways request={request} reload={fn()}/>);await screen.findByText('Prize wheel');fireEvent.click(screen.getByText('Показать ещё'));await screen.findByText('Next');expect(screen.getByText('Prize wheel')).to.be.ok;
});
