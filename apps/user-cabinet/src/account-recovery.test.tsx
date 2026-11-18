import React from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn} from "@vitest/spy";
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {AccountRecovery,AccountSecurity,accountLink} from './account-recovery';
afterEach(()=>{cleanup();history.replaceState(null,'','#overview')});
it('uses the fragment token only after an explicit confirmation',async()=>{
 history.replaceState(null,'','#verify-email?token=private-token');
 expect(accountLink()).to.deep.equal({kind:'verify-email',token:'private-token'});
 const request=fn(async(_p:string,_o?:RequestInit)=>({message:'Email подтверждён'}));
 render(<AccountRecovery link={accountLink()!} request={request} onClose={()=>{}}/>);
 expect(request.mock.calls).to.be.empty;fireEvent.click(screen.getByRole('button',{name:'Подтвердить почту'}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).to.equal('Email подтверждён'));
 expect(request.mock.calls[0][0]).to.equal('/api/auth/email/verification/confirm');
 expect(JSON.parse(String(request.mock.calls[0][1]!.body))).to.deep.equal({token:'private-token'});
});
it('blocks mismatched passwords and removes inputs after success',async()=>{
 const request=fn(async(_p:string,_o?:RequestInit)=>({message:'Пароль изменён'}));
 render(<AccountRecovery link={{kind:'password-reset',token:'one-use-token'}} request={request} onClose={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('Новый пароль'),{target:{value:'new-password'}});
 fireEvent.change(screen.getByLabelText('Повторите пароль'),{target:{value:'other-password'}});
 fireEvent.click(screen.getByRole('button',{name:'Изменить пароль'}));
 expect(request.mock.calls).to.be.empty;expect(screen.getByRole('alert').textContent).to.equal('Пароли не совпадают');
 fireEvent.change(screen.getByLabelText('Повторите пароль'),{target:{value:'new-password'}});
 fireEvent.click(screen.getByRole('button',{name:'Изменить пароль'}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).to.equal('Пароль изменён'));
 expect(screen.queryByLabelText('Новый пароль')).to.be.null;expect(request.mock.calls[0][0]).to.equal('/api/auth/password/reset/confirm');
});
it('does not offer password assignment to an OAuth account',async()=>{
 const request=fn(async()=>({email:'owner@example.test',verified:false,password_enabled:false,mail_enabled:true}));
 render(<AccountSecurity request={request} onPasswordChanged={()=>{}}/>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'Подтвердить email'})).to.be.ok);
 expect(screen.queryByLabelText('Новый пароль')).to.be.null;
});
