import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {AccountRecovery,AccountSecurity,accountLink} from './account-recovery';
afterEach(()=>{cleanup();history.replaceState(null,'','#overview')});
it('uses the fragment token only after an explicit confirmation',async()=>{
 history.replaceState(null,'','#verify-email?token=private-token');
 expect(accountLink()).toEqual({kind:'verify-email',token:'private-token'});
 const request=vi.fn(async(_p:string,_o?:RequestInit)=>({message:'Email подтверждён'}));
 render(<AccountRecovery link={accountLink()!} request={request} onClose={()=>{}}/>);
 expect(request).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Подтвердить почту'}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('Email подтверждён'));
 expect(request.mock.calls[0][0]).toBe('/api/auth/email/verification/confirm');
 expect(JSON.parse(String(request.mock.calls[0][1]!.body))).toEqual({token:'private-token'});
});
it('blocks mismatched passwords and removes inputs after success',async()=>{
 const request=vi.fn(async(_p:string,_o?:RequestInit)=>({message:'Пароль изменён'}));
 render(<AccountRecovery link={{kind:'password-reset',token:'one-use-token'}} request={request} onClose={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('Новый пароль'),{target:{value:'new-password'}});
 fireEvent.change(screen.getByLabelText('Повторите пароль'),{target:{value:'other-password'}});
 fireEvent.click(screen.getByRole('button',{name:'Изменить пароль'}));
 expect(request).not.toHaveBeenCalled();expect(screen.getByRole('alert').textContent).toBe('Пароли не совпадают');
 fireEvent.change(screen.getByLabelText('Повторите пароль'),{target:{value:'new-password'}});
 fireEvent.click(screen.getByRole('button',{name:'Изменить пароль'}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('Пароль изменён'));
 expect(screen.queryByLabelText('Новый пароль')).toBeNull();expect(request.mock.calls[0][0]).toBe('/api/auth/password/reset/confirm');
});
it('does not offer password assignment to an OAuth account',async()=>{
 const request=vi.fn(async()=>({email:'owner@example.test',verified:false,password_enabled:false,mail_enabled:true}));
 render(<AccountSecurity request={request} onPasswordChanged={()=>{}}/>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'Подтвердить email'})).toBeTruthy());
 expect(screen.queryByLabelText('Новый пароль')).toBeNull();
});
