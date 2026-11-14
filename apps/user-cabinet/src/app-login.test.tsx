import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {AppLogin} from './app-login';
afterEach(cleanup);
it('issues a one-use link and opens the https trampoline',async()=>{
 const request=vi.fn().mockResolvedValue({deep_link:'corgi://login?base=x&code=abc',open_url:'https://api.example/api/app/open?code=abc',expires_in:300});
 const open=vi.fn();
 render(<AppLogin request={request} open={open}/>);
 fireEvent.click(screen.getByText('Войти в приложение'));
 await waitFor(()=>expect(open).toHaveBeenCalledWith('https://api.example/api/app/open?code=abc'));
 expect(request).toHaveBeenCalledWith('/api/me/app-login',{method:'POST'});
 expect(screen.getByRole('status').textContent).toContain('5 мин');
 expect(screen.getByText('Открыть напрямую').getAttribute('href')).toBe('corgi://login?base=x&code=abc');
});
it('shows an error and does not navigate when issuing fails',async()=>{
 const open=vi.fn();
 render(<AppLogin request={vi.fn().mockRejectedValue(new Error('Нужно войти'))} open={open}/>);
 fireEvent.click(screen.getByText('Войти в приложение'));
 await screen.findByRole('alert');expect(open).not.toHaveBeenCalled();
});
