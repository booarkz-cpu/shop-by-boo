import React from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn} from "@vitest/spy";
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {SurveyCard,Surveys} from './surveys';
afterEach(cleanup);
const row={id:1,title:'Опрос',description:'',phase:'open',ends_at:'2030-01-01T00:00:00Z',response_count:0,max_responses:10,reward_amount:'5',currency:'RUB',questions:[{text:'Выберите',kind:'single',options:['Первый','Второй']},{text:'Комментарий',kind:'text',options:[]}],submitted:false,statistics:null};
it('requires all answers and sends a single canonical payload',async()=>{
 const request=fn(async(_path:string,_opts?:RequestInit)=>({...row,submitted:true})),done=fn(async()=>{});
 render(<SurveyCard row={row} request={request} onDone={done}/>);
 fireEvent.click(screen.getByLabelText('Первый'));
 fireEvent.change(screen.getByLabelText('Ответ на вопрос 2'),{target:{value:'Мой ответ'}});
 fireEvent.click(screen.getByRole('button',{name:'Отправить ответы'}));fireEvent.click(screen.getByRole('button',{name:'Отправить ответы'}));
 await waitFor(()=>expect(done.mock.calls).to.have.lengthOf(1));expect(request.mock.calls).to.have.lengthOf(1);
 expect(JSON.parse(String(request.mock.calls[0][1]?.body))).to.deep.equal({answers:[{choices:[0],text:''},{choices:[],text:'Мой ответ'}]});
});
it('preserves answers when the response is lost',async()=>{
 const request=fn(async()=>{throw Error('Повторите отправку')}),done=fn(async()=>{});
 render(<SurveyCard row={row} request={request} onDone={done}/>);fireEvent.click(screen.getByLabelText('Второй'));
 fireEvent.change(screen.getByLabelText('Ответ на вопрос 2'),{target:{value:'Сохранить'}});fireEvent.click(screen.getByRole('button',{name:'Отправить ответы'}));
 await waitFor(()=>expect(screen.getByRole('alert').textContent).to.equal('Повторите отправку'));
 expect((screen.getByLabelText('Ответ на вопрос 2') as HTMLInputElement).value).to.equal('Сохранить');
 expect(screen.queryByLabelText('Результаты опроса')).to.be.null;
});
it('loads the next page without replacing existing surveys',async()=>{
 const request=fn(async(path:string)=>path.endsWith('after=0')?{items:[row],next_after:1}:{items:[{...row,id:2,title:'Другой опрос'}],next_after:null});
 render(<Surveys request={request} reload={async()=>{}}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Показать ещё'}));await screen.findByText('Другой опрос');expect(screen.getByText('Опрос')).to.be.ok;
});
