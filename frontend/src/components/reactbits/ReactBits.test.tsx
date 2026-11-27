import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CountUp from './CountUp';
import AnimatedList from './AnimatedList';
import SpotlightCard from './SpotlightCard';
import ShinyText from './ShinyText';

function media(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches,
      media: '',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

test('CountUp exposes the exact measured value and updates immediately with reduced effects', () => {
  media(true);
  const { rerender } = render(<CountUp to={15} />);
  expect(screen.getByLabelText('15')).toHaveTextContent('15');
  rerender(<CountUp to={14} />);
  expect(screen.getByLabelText('14')).toHaveTextContent('14');
});

test('CountUp finishes within its duration and never restarts for polling updates', () => {
  media(false);
  vi.useFakeTimers();
  const frames: FrameRequestCallback[] = [];
  const raf = vi.fn((callback: FrameRequestCallback) => { frames.push(callback); return frames.length; });
  vi.stubGlobal('requestAnimationFrame', raf);
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  const { rerender, unmount } = render(<CountUp to={15} duration={.75} />);
  vi.advanceTimersByTime(0);
  frames.shift()!(100);
  frames.shift()!(350);
  const current = Number(screen.getByLabelText('15').textContent);
  expect(current).toBeGreaterThan(0);
  expect(current).toBeLessThan(15);
  frames.shift()!(850);
  expect(screen.getByLabelText('15')).toHaveTextContent('15');
  const scheduled = raf.mock.calls.length;
  rerender(<CountUp to={15} duration={.75} />);
  rerender(<CountUp to={14} duration={.75} />);
  expect(screen.getByLabelText('14')).toHaveTextContent('14');
  expect(raf).toHaveBeenCalledTimes(scheduled);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

test('AnimatedList preserves natural tab order and selects only a real item', async () => {
  media(true);
  const select = vi.fn();
  const user = userEvent.setup();
  render(
    <>
      <button>Avant</button>
      <AnimatedList items={['B0 bottle', 'T2 bottle']} onItemSelect={select} />
      <button>Après</button>
    </>,
  );
  await user.tab();
  expect(screen.getByRole('button', { name: 'Avant' })).toHaveFocus();
  await user.keyboard('{ArrowDown}');
  expect(select).not.toHaveBeenCalled();
  await user.tab();
  expect(screen.getByRole('button', { name: 'B0 bottle' })).toHaveFocus();
  await user.keyboard('{ArrowDown}');
  expect(screen.getByRole('button', { name: 'T2 bottle' })).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(select).toHaveBeenCalledWith('T2 bottle', 1);
  await user.tab();
  expect(screen.getByRole('button', { name: 'Après' })).toHaveFocus();
});

test('AnimatedList has a real empty state and semantic noninteractive items', () => {
  media(true);
  const { rerender } = render(<AnimatedList />);
  expect(screen.getByRole('list')).toBeEmptyDOMElement();
  rerender(<AnimatedList items={['Inspection réelle']} />);
  expect(screen.getAllByRole('listitem')).toHaveLength(1);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

test('Spotlight avoids pointer work and ShinyText is static for reduced effects', () => {
  media(true);
  render(
    <>
      <SpotlightCard>Modèle disponible</SpotlightCard>
      <ShinyText text="ResilientInspect" />
    </>,
  );
  const card = screen.getByText('Modèle disponible');
  fireEvent.mouseMove(card, { clientX: 80, clientY: 40 });
  expect(card.style.getPropertyValue('--mouse-x')).toBe('');
  expect(screen.getByText('ResilientInspect')).toHaveClass('disabled');
});
