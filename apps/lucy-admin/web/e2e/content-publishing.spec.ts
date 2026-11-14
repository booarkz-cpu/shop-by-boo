import {test,expect} from '@playwright/test';

test('editor publishes safely, preserves old text while editing and archives public content',async({page,context})=>{
 await page.addInitScript(()=>localStorage.setItem('rw_lang','ru'));
 await page.goto('/');await page.getByLabel('Email',{exact:true}).fill('browser@example.test');await page.getByLabel('Пароль',{exact:true}).fill('browser-only-password');await page.getByRole('button',{name:'Войти',exact:true}).click();
 await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/admin/pages')&&r.request().method()==='GET'),page.getByRole('button',{name:/Новости и страницы/}).click()]);
 await page.getByLabel('Slug',{exact:true}).fill('browser-terms');await page.getByRole('combobox',{name:'Тип страницы',exact:true}).click();await page.getByRole('option',{name:'Юридическая страница',exact:true}).click();await page.getByLabel('Заголовок',{exact:true}).fill('Browser terms');
 const hostile='<img src=x onerror="window.cmsInjected=1">';await page.getByLabel('Текст блока',{exact:true}).fill(hostile);
 await page.getByRole('button',{name:'Предпросмотр',exact:true}).click();await expect(page.getByLabel('Предпросмотр страницы')).toContainText(hostile);
 expect(await page.evaluate(()=>(window as any).cmsInjected)).toBeUndefined();await page.getByRole('button',{name:'Сохранить черновик',exact:true}).click();
 await expect(page.getByText(/Страница #\d+, версия 1/)).toBeVisible();await page.getByRole('button',{name:'Опубликовать',exact:true}).click();await expect(page.getByText(/Страница #\d+, версия 2/)).toBeVisible();
 const customer=await context.newPage();await customer.goto('/cabinet/#page/browser-terms');await expect(customer.getByRole('heading',{name:'Browser terms',exact:true})).toBeVisible();await expect(customer.getByText(hostile,{exact:true})).toBeVisible();expect(await customer.evaluate(()=>(window as any).cmsInjected)).toBeUndefined();
 await page.getByLabel('Заголовок',{exact:true}).fill('Edited terms');await page.getByRole('button',{name:'Сохранить черновик',exact:true}).click();await expect(page.getByText(/Страница #\d+, версия 3/)).toBeVisible();await customer.reload();await expect(customer.getByRole('heading',{name:'Browser terms',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Опубликовать',exact:true}).click();await expect(page.getByText(/Страница #\d+, версия 4/)).toBeVisible();await customer.reload();await expect(customer.getByRole('heading',{name:'Edited terms',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Снять с публикации',exact:true}).click();await expect(page.getByText(/Страница #\d+, версия 5/)).toBeVisible();await customer.reload();await expect(customer.getByRole('alert')).toBeVisible();await customer.close();
});
