import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { health, metadata } from './test/fixtures';
import type { PortalRole } from './portal/session';

const state = vi.hoisted(() => ({ authenticated: true, role: 'admin' as PortalRole, permissions: ['inspect', 'readiness', 'admin', 'audit'] }));
vi.mock('./portal/session', async (original) => ({ ...(await original<typeof import('./portal/session')>()), PORTAL_MODE: true }));
vi.mock('./portal/Auth', async (original) => ({
  ...(await original<typeof import('./portal/Auth')>()),
  usePortalAuth: () => state.authenticated ? ({ user: { id: 'test', name: 'Test User', email: null, enabled: true, role: state.role, permissions: state.permissions }, logout: vi.fn() }) : null,
}));
vi.mock('./studio/useSystem', () => ({ useSystem: () => ({ health, metadata, loading: false, error: null, refresh: vi.fn(), timings: [] }) }));
import App from './App';

beforeEach(() => {
  state.authenticated = true;
  window.history.replaceState(null, '', '/');
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0 }))));
});

test('visual identity follows authenticated role changes and preserves the light/dark preference', () => {
  state.role = 'admin'; state.permissions = ['inspect', 'readiness', 'admin', 'audit'];
  localStorage.setItem('ri.theme', 'light');
  localStorage.setItem('ri.role', 'ai_engineer');
  const { rerender } = render(<App />);
  expect(document.querySelector('.app-shell')).toHaveAttribute('data-role', 'admin');
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  state.role = 'ai_engineer'; state.permissions = ['inspect', 'readiness'];
  rerender(<App />);
  expect(document.querySelector('.app-shell')).toHaveAttribute('data-role', 'ai_engineer');
  expect(screen.getByRole('link', { name: /Ingénieur IA/ })).toBeInTheDocument();
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  expect(screen.queryByRole('link', { name: 'Administration' })).not.toBeInTheDocument();
  state.authenticated = false;
  rerender(<App />);
  expect(document.querySelector('.app-shell')).not.toHaveAttribute('data-role');
});

test.each([
  ['admin', ['inspect', 'readiness', 'admin', 'audit'], ['Smart Inspection', 'Comparison Lab', 'System Monitor', 'Administration', 'Audit']],
  ['ai_engineer', ['inspect', 'readiness'], ['Smart Inspection', 'Comparison Lab', 'System Monitor']],
  ['operator', ['inspect'], ['Smart Inspection', 'Comparison Lab']],
  ['auditor', ['audit'], ['Audit']],
] as [PortalRole, string[], string[]][])(
  '%s sees only authorized navigation and dashboard actions', (role, permissions, expected) => {
    state.role = role; state.permissions = permissions;
    render(<App />);
    const nav = within(screen.getByRole('navigation', { name: 'Navigation principale' }));
    for (const name of ['Smart Inspection', 'Comparison Lab', 'System Monitor', 'Administration', 'Audit']) {
      expect(!!nav.queryByRole('link', { name })).toBe(expected.includes(name));
    }
    expect(!!screen.queryByRole('button', { name: 'Nouvelle inspection' })).toBe(permissions.includes('inspect'));
    expect(nav.getByRole('link', { name: 'Batch Inspection' })).toBeInTheDocument();
    expect(nav.getByRole('link', { name: 'Mon profil' })).toBeInTheDocument();
  },
);

test('an unauthorized direct URL retains the access denied screen', () => {
  state.role = 'operator'; state.permissions = ['inspect'];
  window.history.replaceState(null, '', '/#admin');
  render(<App />);
  expect(screen.getByRole('alert')).toHaveTextContent('ACCÈS 403');
  expect(screen.queryByRole('button', { name: 'Nouvelle inspection' })).not.toBeInTheDocument();
});

test('desktop navigation is expanded by default and demo mode preserves the user choice', async () => {
  state.role = 'admin'; state.permissions = ['inspect', 'readiness', 'admin', 'audit'];
  const user = userEvent.setup();
  render(<App />);
  expect(document.querySelector('.app-shell')).not.toHaveClass('sidebar-collapsed');
  await user.click(screen.getByRole('button', { name: 'Mode démonstration' }));
  expect(document.querySelector('.app-shell')).not.toHaveClass('sidebar-collapsed');
  await user.click(screen.getByRole('button', { name: 'Réduire la navigation' }));
  expect(document.querySelector('.app-shell')).toHaveClass('sidebar-collapsed');
  await user.click(screen.getByRole('button', { name: 'Mode démonstration' }));
  expect(document.querySelector('.app-shell')).toHaveClass('sidebar-collapsed');
});

test('mobile navigation restores focus and scroll on Escape and traps the Tab boundary', async () => {
  state.role = 'admin'; state.permissions = ['inspect', 'readiness', 'admin', 'audit'];
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  // jsdom has no layout; visible controls are exercised in the real browser too.
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue([{} as DOMRect] as unknown as DOMRectList);
  const user = userEvent.setup();
  render(<App />);
  const opener = screen.getByRole('button', { name: 'Ouvrir la navigation' });
  expect(document.querySelector('.sidebar')).toHaveAttribute('inert');
  fireEvent.click(opener);
  const drawer = screen.getByRole('dialog', { name: 'Navigation du studio' });
  const close = within(drawer).getByRole('button', { name: 'Fermer la navigation' });
  expect(close).toHaveFocus();
  expect(document.body.style.overflow).toBe('hidden');
  await user.tab({ shift: true });
  expect(within(drawer).getByRole('button', { name: 'Réduire la navigation' })).toHaveFocus();
  await user.tab();
  expect(close).toHaveFocus();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
  expect(document.body.style.overflow).toBe('');
  expect(document.querySelector('.main-shell')).not.toHaveAttribute('inert');
});
