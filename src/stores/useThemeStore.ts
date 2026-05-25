import { create } from 'zustand';
import { flushSync } from 'react-dom';

export type Theme = 'dark' | 'light';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: (event: React.MouseEvent<HTMLElement> | MouseEvent) => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: 'dark',
  setTheme: (theme) => set({ theme }),
  toggleTheme: (event) => {
    const currentTheme = get().theme;
    const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';

    // Fallback if view transitions are not supported
    if (!document.startViewTransition) {
      set({ theme: nextTheme });
      return;
    }

    const x = event.clientX;
    const y = event.clientY;
    
    // Calculate final radius to fully cover screen from cursor click point
    const maxRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y)
    );

    // Pass parameters as CSS variables to root element
    const root = document.documentElement;
    root.style.setProperty('--ripple-x', `${x}px`);
    root.style.setProperty('--ripple-y', `${y}px`);
    root.style.setProperty('--ripple-radius', `${maxRadius}px`);

    // Execute view transition
    const transition = document.startViewTransition(() => {
      // Force synchronous DOM update inside React
      flushSync(() => {
        set({ theme: nextTheme });
      });
    });

    // Add a class during transitioning to handle custom animations
    root.classList.add('theme-transitioning');
    transition.finished.finally(() => {
      root.classList.remove('theme-transitioning');
    });
  },
}));
