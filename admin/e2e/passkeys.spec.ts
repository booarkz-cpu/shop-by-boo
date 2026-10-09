import {test,expect} from '@playwright/test';

test('browser registration, discoverable login, reload and credential deletion',async({page,context})=>{
  const client=await context.newCDPSession(page);
  await client.send('WebAuthn.enable');
  await client.send('WebAuthn.addVirtualAuthenticator',{options:{protocol:'ctap2',transport:'internal',
    hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true}});
  await page.addInitScript(()=>localStorage.setItem('rw_lang','ru'));
  await page.goto('/');
  await page.getByLabel('Email',{exact:true}).fill('browser@example.test');
  await page.getByLabel('Пароль',{exact:true}).fill('browser-only-password');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await page.getByRole('button',{name:/Ключи доступа/}).click();
  await expect(page.getByRole('heading',{name:'Ключи доступа / WebAuthn'})).toBeVisible();
  await page.getByLabel('Название',{exact:true}).fill('Browser authenticator');
  await page.getByLabel('Пароль',{exact:true}).fill('browser-only-password');
  await page.getByRole('button',{name:'Добавить ключ доступа'}).click();
  await expect(page.getByRole('cell',{name:'Browser authenticator'})).toBeVisible({timeout:15000});
  await expect(page.getByLabel('Пароль',{exact:true})).toHaveValue('');
  await page.evaluate(async()=>{
    const csrf=decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('rw_csrf='))?.split('=')[1]||'');
    const response=await fetch('/api/admin/auth/logout',{method:'POST',headers:{'X-CSRF-Token':csrf}});
    if (!response.ok) throw Error('Logout failed');
  });
  await page.reload();
  await page.getByRole('button',{name:'Войти с ключом доступа'}).click();
  await expect(page.getByRole('heading',{name:'Ключи доступа / WebAuthn'})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('cell',{name:'Browser authenticator'})).toBeVisible();
  await page.getByRole('button',{name:'Удалить',exact:true}).click();
  await expect(page.getByText('Ключи ещё не добавлены.')).toBeVisible();
  await client.detach();
});

test('customer passkey ceremonies use browser credentials and a revocable customer session',async({page,context})=>{
  const client=await context.newCDPSession(page);
  await client.send('WebAuthn.enable');
  await client.send('WebAuthn.addVirtualAuthenticator',{options:{protocol:'ctap2',transport:'internal',
    hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true}});
  await page.goto('/');
  const result=await page.evaluate(async()=>{
    const bytes=(s:string)=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
    const encoded=(s:ArrayBuffer)=>btoa(String.fromCharCode(...new Uint8Array(s))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
    async function request(path:string,body?:any){
      const csrf=decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('rw_csrf='))?.split('=')[1]||'');
      const response=await fetch(path,{method:body?'POST':'GET',credentials:'include',
        headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body?JSON.stringify(body):undefined});
      const data=await response.json();if(!response.ok)throw Error(JSON.stringify(data));return data;
    }
    await request('/api/auth/login',{email:'customer@example.test',password:'customer-browser-password'});
    const reg=await request('/api/auth/passkeys/registration/options',{name:'Customer browser',password:'customer-browser-password'});
    const credential=await navigator.credentials.create({publicKey:{...reg.options,challenge:bytes(reg.options.challenge),
      user:{...reg.options.user,id:bytes(reg.options.user.id)},excludeCredentials:[]}}) as PublicKeyCredential;
    const response=credential.response as AuthenticatorAttestationResponse;
    await request('/api/auth/passkeys/registration/verify',{ticket:reg.ticket,credential:{id:credential.id,rawId:encoded(credential.rawId),type:'public-key',
      response:{clientDataJSON:encoded(response.clientDataJSON),attestationObject:encoded(response.attestationObject)}}});
    await request('/api/auth/logout',{});
    const auth=await request('/api/auth/passkeys/login/options',{});
    const assertion=await navigator.credentials.get({publicKey:{...auth.options,challenge:bytes(auth.options.challenge)}}) as PublicKeyCredential;
    const signed=assertion.response as AuthenticatorAssertionResponse;
    await request('/api/auth/passkeys/login/verify',{ticket:auth.ticket,credential:{id:assertion.id,rawId:encoded(assertion.rawId),type:'public-key',
      response:{clientDataJSON:encoded(signed.clientDataJSON),authenticatorData:encoded(signed.authenticatorData),signature:encoded(signed.signature),
        userHandle:encoded(signed.userHandle!)}}});
    const inventory=await request('/api/auth/passkeys');
    await request(`/api/auth/passkeys/${inventory[0].id}/delete`,{password:'customer-browser-password'});
    return {inventory,after:await request('/api/auth/passkeys')};
  });
  expect(result.inventory).toHaveLength(1);
  expect(result.inventory[0].name).toBe('Customer browser');
  expect(result.after).toHaveLength(0);
  await client.detach();
});
