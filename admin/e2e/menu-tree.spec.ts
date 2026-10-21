import {test,expect} from '@playwright/test';

test('menu editor creates folders, previews nested buttons and prevents stale saves',async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('rw_lang','ru'));
 await page.goto('/');await page.getByLabel('Email',{exact:true}).fill('browser@example.test');await page.getByLabel('Пароль',{exact:true}).fill('browser-only-password');await page.getByRole('button',{name:'Войти',exact:true}).click();
 await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/admin/content')&&r.request().method()==='GET'),page.getByRole('button',{name:/Дерево кнопок/}).click()]);
 await page.getByLabel('Название кнопки бота',{exact:true}).fill('Browser folder');await page.getByRole('combobox',{name:'Стиль бота',exact:true}).click();await page.getByRole('option',{name:'Синий',exact:true}).click();
 await page.getByRole('button',{name:'Сохранить кнопку бота',exact:true}).click();await expect(page.getByRole('status')).toContainText('Кнопка сохранена');
 await page.evaluate(async()=>{const r=await fetch('/api/admin/fields',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('rw_csrf='))?.split('=')[1]||'')},body:JSON.stringify({key:'browser_menu_help',label:'Help',value:'Menu help'})});if(!r.ok)throw new Error('Cannot create field')});
 await page.getByLabel('Название кнопки бота',{exact:true}).fill('Browser link');await page.getByRole('combobox',{name:'Тип кнопки бота',exact:true}).click();await page.getByRole('option',{name:'Поле',exact:true}).click();await page.getByLabel('URL или ключ поля',{exact:true}).fill('browser_menu_help');await page.getByRole('combobox',{name:'Родитель бота',exact:true}).click();await page.getByRole('option',{name:/Browser folder/}).click();
 await page.getByRole('button',{name:'Сохранить кнопку бота',exact:true}).click();await expect(page.getByRole('button',{name:/#\d+ Browser link/})).toBeVisible();
 await page.getByRole('button',{name:'Добавить корневую кнопку',exact:true}).click();
 const folder=page.locator('fieldset').filter({has:page.locator('legend').filter({hasText:/^Уровень 1:/})}).last();
 await folder.getByLabel('Название кнопки',{exact:true}).fill('Nested menu');await folder.getByRole('button',{name:'Добавить дочернюю кнопку',exact:true}).click();
 const child=page.locator('fieldset').filter({has:page.locator('legend').filter({hasText:/^Уровень 2:/})}).last();
 await child.getByLabel('Название кнопки',{exact:true}).fill('Plans inside');await child.getByRole('combobox',{name:/Действие /}).click();await page.getByRole('option',{name:'Тарифы',exact:true}).click();
 const preview=page.getByLabel('Меню приложения',{exact:true});await preview.getByRole('button',{name:'Nested menu ›',exact:true}).click();await expect(preview.getByRole('button',{name:'Plans inside',exact:true})).toBeVisible();await preview.getByRole('button',{name:'← Назад',exact:true}).click();
 await page.getByRole('button',{name:'Сохранить меню приложения',exact:true}).click();await expect(page.getByRole('status')).toContainText('Меню приложения сохранено');
 // Simulate another operator saving the same menu after this editor loaded it.
 await page.evaluate(async()=>{const config=await (await fetch('/api/admin/content')).json();const r=await fetch('/api/admin/miniapp/menu',{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('rw_csrf='))?.split('=')[1]||'')},body:JSON.stringify({fingerprint:config.miniapp_buttons_fingerprint,buttons:[{id:'other-operator',title:'Other operator',type:'plans'}]})});if(!r.ok)throw new Error('Fixture update failed')});
 await page.getByRole('button',{name:'Сохранить меню приложения',exact:true}).click();await expect(page.locator('.content-wrap').getByRole('alert')).toContainText('изменено');
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Загрузить актуальное меню',exact:true}).click();await expect(page.getByRole('status')).toContainText('Загружено актуальное меню');await expect(preview.getByRole('button',{name:'Other operator',exact:true})).toBeVisible();
});
