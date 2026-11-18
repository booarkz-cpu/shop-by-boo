import React from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn} from "@vitest/spy";
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {AppLogin} from './app-login';
afterEach(cleanup);
it('issues a one-use link and opens the https trampoline',async()=>{
 const request=fn().mockResolvedValue({deep_link:'corgi://login?base=x&code=abc',open_url:'https://api.example/api/app/open?code=abc',expires_in:300});
 const open=fn();
 render(<AppLogin request={request} open={open}/>);
 fireEvent.click(screen.getByText('Войти в приложение'));
 await waitFor(()=>expect(open.mock.calls).to.deep.include(['https://api.example/api/app/open?code=abc']));
 expect(request.mock.calls).to.deep.include(['/api/me/app-login',{method:'POST'}]);
 expect(screen.getByRole('status').textContent).to.include('5 мин');
 expect(screen.getByText('Открыть напрямую').getAttribute('href')).to.equal('corgi://login?base=x&code=abc');
});
it('shows an error and does not navigate when issuing fails',async()=>{
 const open=fn();
 render(<AppLogin request={fn().mockRejectedValue(new Error('Нужно войти'))} open={open}/>);
 fireEvent.click(screen.getByText('Войти в приложение'));
 await screen.findByRole('alert');expect(open.mock.calls).to.be.empty;
});
