import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';

test('administrator imports a SQLite balance once and sends a previewed bulk notice',async({page})=>{
  const source=execFileSync(process.env.PASSKEY_TEST_PYTHON||'python',['-c',
    "import sqlite3,sys; db=sqlite3.connect(':memory:'); db.execute('CREATE TABLE users(id INTEGER,telegram_id INTEGER,username TEXT,balance TEXT)'); db.execute(\"INSERT INTO users VALUES(991,9001001,'Browser imported','37.50')\"); db.commit(); sys.stdout.buffer.write(db.serialize())"]);
  await page.addInitScript(()=>localStorage.setItem('rw_lang','ru'));
  await page.goto('/');
  await page.getByLabel('Email',{exact:true}).fill('browser@example.test');
  await page.getByLabel('Пароль',{exact:true}).fill('browser-only-password');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await Promise.all([page.waitForResponse(response=>response.url().endsWith('/api/admin/customer-operations/import/history')&&response.request().method()==='GET'),
    page.getByRole('button',{name:/Импорт и массовые операции/}).click()]);
  await expect(page.getByRole('heading',{name:'Перенос клиентов из users.db'})).toBeVisible();
  await page.getByLabel('Snapshot SQLite до 5 МБ',{exact:true}).setInputFiles({name:'users.db',mimeType:'application/octet-stream',buffer:source});
  await page.getByRole('button',{name:'Прочитать поля'}).click();
  await expect(page.getByRole('combobox',{name:'Telegram ID',exact:true})).toContainText('telegram_id');
  await page.getByLabel('Зачислить исходный баланс только новым клиентам',{exact:true}).check();
  await page.getByRole('button',{name:'Проверить перенос'}).click();
  await expect(page.getByRole('heading',{name:'Результат проверки импорта'})).toBeVisible();
  await expect(page.getByText(/Зачисление: 37.50 RUB/)).toBeVisible();
  await expect(page.getByRole('button',{name:'Применить перенос'})).toBeDisabled();
  await page.getByLabel('Я проверил все строки, валюту и достоверность исходного остатка',{exact:true}).check();
  await page.getByRole('button',{name:'Применить перенос'}).click();
  await expect(page.getByRole('status')).toContainText('создано 1');
  await page.getByRole('button',{name:'Проверить перенос'}).click();
  await expect(page.getByText(/уже перенесено: 1/)).toBeVisible();
  await expect(page.getByText(/Зачисление: 0.00 RUB/)).toBeVisible();
  await page.getByRole('button',{name:'Отменить preview'}).click();
  const userId=await page.evaluate(async()=>{
    const rows=await (await fetch('/api/admin/customer-operations/import/history')).json();
    return rows.find((row:any)=>row.status==='applied').result.user_ids[0];
  });
  await page.getByLabel('ID клиентов магазина',{exact:true}).fill(String(userId));
  await page.getByRole('combobox',{name:'Действие',exact:true}).click();
  await page.getByRole('option',{name:'Отправить уведомление в кабинет',exact:true}).click();
  await page.getByLabel('Причина',{exact:true}).fill('Import welcome');
  await page.getByLabel('Заголовок',{exact:true}).fill('Welcome');
  await page.getByLabel('Текст',{exact:true}).fill('Your profile was transferred.');
  await page.getByRole('button',{name:'Проверить операцию'}).click();
  await expect(page.getByRole('button',{name:'Применить операцию'})).toBeDisabled();
  await page.getByLabel('Я проверил список и действие',{exact:true}).check();
  await page.getByRole('button',{name:'Применить операцию'}).click();
  await expect(page.getByRole('status')).toContainText('обработано клиентов 1');
});
