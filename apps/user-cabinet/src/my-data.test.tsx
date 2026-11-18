import React from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {fn} from "@vitest/spy";
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MyData,exportName} from './my-data';
afterEach(cleanup);

it('downloads the export as a JSON file named by the date', async () => {
  const request = fn(async (_p: string, _o?: RequestInit) => ({user: {id: 7}, payments: [{id: 1}]}));
  const save = fn();
  render(<MyData request={request} onDeleted={() => {}} save={save}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Скачать мои данные'}));
  await waitFor(() => expect(screen.getByRole('status').textContent).to.equal('Файл с вашими данными сохранён'));
  expect(request.mock.calls[0][0]).to.equal('/api/me/privacy/export');
  expect(save.mock.calls[0][0]).to.equal(exportName());
  expect(JSON.parse(save.mock.calls[0][1])).to.deep.equal({user: {id: 7}, payments: [{id: 1}]});
  expect(exportName(new Date('2026-11-15T10:00:00Z'))).to.equal('corgi-lusi-my-data-2026-11-15.json');
});

it('deletes the account only after the word is typed', async () => {
  const request = fn(async (_p: string, _o?: RequestInit) => ({anonymized: true}));
  const onDeleted = fn();
  render(<MyData request={request} onDeleted={onDeleted} save={() => {}}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Удалить учётную запись'}));
  fireEvent.click(screen.getByRole('button', {name: 'Удалить навсегда'}));
  expect(request.mock.calls).to.be.empty;
  expect(screen.getByRole('alert').textContent).to.include('УДАЛИТЬ');
  fireEvent.change(screen.getByLabelText('Впишите УДАЛИТЬ'), {target: {value: 'УДАЛИТЬ'}});
  fireEvent.click(screen.getByRole('button', {name: 'Удалить навсегда'}));
  await waitFor(() => expect(onDeleted.mock.calls).not.to.be.empty);
  expect(request.mock.calls[0]).to.deep.equal(['/api/me/privacy/account', {method: 'DELETE'}]);
});

it('shows the server reason when deletion is refused and keeps the account', async () => {
  const request = fn(async () => { throw new Error('Active subscription must expire before account deletion'); });
  const onDeleted = fn();
  render(<MyData request={request} onDeleted={onDeleted} save={() => {}}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Удалить учётную запись'}));
  fireEvent.change(screen.getByLabelText('Впишите УДАЛИТЬ'), {target: {value: 'УДАЛИТЬ'}});
  fireEvent.click(screen.getByRole('button', {name: 'Удалить навсегда'}));
  await waitFor(() => expect(screen.getByRole('alert').textContent).to.equal('Active subscription must expire before account deletion'));
  expect(onDeleted.mock.calls).to.be.empty;
  fireEvent.click(screen.getByRole('button', {name: 'Отмена'}));
  expect(screen.queryByLabelText('Впишите УДАЛИТЬ')).to.be.null;
});
