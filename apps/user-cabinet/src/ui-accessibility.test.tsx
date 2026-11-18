import React from 'react';
import {afterEach, it} from "node:test";
import {expect} from "chai";
import {cleanup, render, screen} from '@testing-library/react';
import {Meter} from './ui';

afterEach(cleanup);

it('announces missing data without claiming a numerical measurement', () => {
  const view = render(<Meter label="Использованный трафик" value={null}/>);
  expect(screen.queryByRole('meter')).to.be.null;
  expect(screen.getByRole('img', {name: 'Использованный трафик: нет данных'})).to.be.ok;
  view.rerender(<Meter label="Использованный трафик" value={0}/>);
  const meter = screen.getByRole('meter', {name: 'Использованный трафик'});
  expect(meter.getAttribute('aria-valuenow')).to.equal('0');
  expect(meter.getAttribute('aria-valuemin')).to.equal('0');
  expect(meter.getAttribute('aria-valuemax')).to.equal('100');
  expect(screen.queryByRole('img')).to.be.null;
  view.rerender(<Meter label="Использованный трафик" value={null}/>);
  expect(screen.queryByRole('meter')).to.be.null;
  expect(screen.getByRole('img', {name: /нет данных/})).to.be.ok;
});

it('keeps measurements within the announced range', () => {
  const view = render(<Meter label="Срок" value={-1}/>);
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).to.equal('0');
  view.rerender(<Meter label="Срок" value={.5}/>);
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).to.equal('50');
  view.rerender(<Meter label="Срок" value={2}/>);
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).to.equal('100');
});

it('treats non-finite values as unavailable instead of announcing NaN or Infinity', () => {
  const view = render(<Meter label="Трафик" value={NaN}/>);
  expect(screen.queryByRole('meter')).to.be.null;
  view.rerender(<Meter label="Трафик" value={Infinity}/>);
  expect(screen.queryByRole('meter')).to.be.null;
  expect(screen.getByRole('img', {name: 'Трафик: нет данных'})).to.be.ok;
});
