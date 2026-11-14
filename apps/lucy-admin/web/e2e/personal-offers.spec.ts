import {test,expect} from '@playwright/test';

test('administrator creates an atomic personal offer visible to its customer',async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('rw_lang','ru'));
 await page.goto('/');await page.getByLabel('Email',{exact:true}).fill('browser@example.test');await page.getByLabel('Пароль',{exact:true}).fill('browser-only-password');await page.getByRole('button',{name:'Войти',exact:true}).click();
 await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/admin/promo-audiences')),page.getByRole('button',{name:/Группы и предложения/}).click()]);
 await page.getByLabel('Код предложения',{exact:true}).fill('BROWSER_ONLY');await page.getByLabel('Название предложения',{exact:true}).fill('Personal welcome');await page.getByLabel('ID получателей',{exact:true}).fill('1');
 await page.getByRole('button',{name:'Сохранить предложение',exact:true}).click();await expect(page.getByRole('button',{name:/Personal welcome · включено · v1/})).toBeVisible();
 const result=await page.evaluate(async()=>{
  const csrf=decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('rw_csrf='))?.split('=')[1]||'');
  const login=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({email:'customer@example.test',password:'customer-browser-password'})});
  const offers=await (await fetch('/api/me/offers')).json();return {login:login.status,offers};
 });expect(result.login).toBe(200);expect(result.offers.items.some((x:any)=>x.code==='BROWSER_ONLY')).toBe(true);
});
