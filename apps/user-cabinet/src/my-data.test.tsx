import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MyData,exportName} from './my-data';
afterEach(cleanup);

it('downloads the export as a JSON file named by the date', async () => {
  const request = vi.fn(async (_p: string, _o?: RequestInit) => ({user: {id: 7}, payments: [{id: 1}]}));
  const save = vi.fn();
  render(<MyData request={request} onDeleted={() => {}} save={save}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Скачать мои данные'}));
  await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Файл с вашими данными сохранён'));
  expect(request.mock.calls[0][0]).toBe('/api/me/privacy/export');
  expect(save.mock.calls[0][0]).toBe(exportName());
  expect(JSON.parse(save.mock.calls[0][1])).toEqual({user: {id: 7}, payments: [{id: 1}]});
  expect(exportName(new Date('2026-11-15T10:00:00Z'))).toBe('corgi-lusi-my-data-2026-11-15.json');
});

it('deletes the account only after the word is typed', async () => {
  const request = vi.fn(async (_p: string, _o?: RequestInit) => ({anonymized: true}));
  const onDeleted = vi.fn();
  render(<MyData request={request} onDeleted={onDeleted} save={() => {}}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Удалить учётную запись'}));
  fireEvent.click(screen.getByRole('button', {name: 'Удалить навсегда'}));
  expect(request).not.toHaveBeenCalled();
  expect(screen.getByRole('alert').textContent).toContain('УДАЛИТЬ');
  fireEvent.change(screen.getByLabelText('Впишите УДАЛИТЬ'), {target: {value: 'УДАЛИТЬ'}});
  fireEvent.click(screen.getByRole('button', {name: 'Удалить навсегда'}));
  await waitFor(() => expect(onDeleted).toHaveBeenCalled());
  expect(request.mock.calls[0]).toEqual(['/api/me/privacy/account', {method: 'DELETE'}]);
});

it('shows the server reason when deletion is refused and keeps the account', async () => {
  const request = vi.fn(async () => { throw new Error('Active subscription must expire before account deletion'); });
  const onDeleted = vi.fn();
  render(<MyData request={request} onDeleted={onDeleted} save={() => {}}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Удалить учётную запись'}));
  fireEvent.change(screen.getByLabelText('Впишите УДАЛИТЬ'), {target: {value: 'УДАЛИТЬ'}});
  fireEvent.click(screen.getByRole('button', {name: 'Удалить навсегда'}));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Active subscription must expire before account deletion'));
  expect(onDeleted).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', {name: 'Отмена'}));
  expect(screen.queryByLabelText('Впишите УДАЛИТЬ')).toBeNull();
});
