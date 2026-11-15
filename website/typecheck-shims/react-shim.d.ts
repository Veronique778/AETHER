/**
 * OFFLINE TYPECHECK SHIM – used only by tsconfig.offline.json in environments where
 * @types/react cannot be installed. It types hooks/components strictly but treats
 * intrinsic element attributes loosely. The real check is `npm run typecheck`.
 */
declare module 'react' {
  export type ReactNode = string | number | bigint | boolean | null | undefined | ReactElement | Iterable<ReactNode> | Promise<ReactNode>;
  export interface ReactElement { type: unknown; props: unknown; key: string | null }
  export type Key = string | number;
  export type SetStateAction<S> = S | ((prev: S) => S);
  export type Dispatch<A> = (value: A) => void;
  export interface RefObject<T> { current: T }
  export type CSSProperties = Record<string, string | number | undefined>;
  export interface Context<T> { Provider: (props: { value: T; children?: ReactNode }) => ReactNode; _t?: T }
  export function createContext<T>(defaultValue: T): Context<T>;
  export function useContext<T>(ctx: Context<T>): T;
  export function useSyncExternalStore<T>(subscribe: (onChange: () => void) => () => void, getSnapshot: () => T, getServerSnapshot?: () => T): T;
  export function useState<S>(initial: S | (() => S)): [S, Dispatch<SetStateAction<S>>];
  export function useState<S = undefined>(): [S | undefined, Dispatch<SetStateAction<S | undefined>>];
  export function useEffect(effect: () => void | (() => void), deps?: readonly unknown[]): void;
  export function useLayoutEffect(effect: () => void | (() => void), deps?: readonly unknown[]): void;
  export function useMemo<T>(factory: () => T, deps: readonly unknown[]): T;
  export function useCallback<T extends (...args: never[]) => unknown>(cb: T, deps: readonly unknown[]): T;
  export function useRef<T>(initial: T): RefObject<T>;
  export function useRef<T>(initial: T | null): RefObject<T | null>;
  export function useRef<T = undefined>(): RefObject<T | undefined>;
  export function useId(): string;
  export function useReducer<S, A>(reducer: (s: S, a: A) => S, initial: S): [S, Dispatch<A>];
  export type ComponentType<P = object> = (props: P) => ReactNode;
  export const StrictMode: (props: { children?: ReactNode }) => ReactNode;
  export function lazy<P = object>(load: () => Promise<{ default: (props: P) => ReactNode }>): (props: P) => ReactNode;
  export const Suspense: (props: { fallback?: ReactNode; children?: ReactNode }) => ReactNode;
  export const Fragment: (props: { children?: ReactNode }) => ReactNode;

  export interface SyntheticEvent<T = Element, E = Event> {
    currentTarget: T & EventTarget; target: EventTarget & T; nativeEvent: E;
    preventDefault(): void; stopPropagation(): void; type: string;
  }
  export interface MouseEvent<T = Element> extends SyntheticEvent<T> { clientX: number; clientY: number; button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }
  export interface PointerEvent<T = Element> extends MouseEvent<T> { pointerId: number }
  export interface DragEvent<T = Element> extends MouseEvent<T> { dataTransfer: DataTransfer }
  export interface WheelEvent<T = Element> extends MouseEvent<T> { deltaY: number }
  export interface KeyboardEvent<T = Element> extends SyntheticEvent<T> { key: string; code: string; repeat: boolean; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }
  export interface ChangeEvent<T = Element> extends SyntheticEvent<T> { target: EventTarget & T }
  export interface FormEvent<T = Element> extends SyntheticEvent<T> {}
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  type Loose = { [attr: string]: any };
  export type HTMLAttributes<T> = Loose & { className?: string; children?: ReactNode; onClick?: (e: MouseEvent<T>) => void };
  export type ButtonHTMLAttributes<T> = HTMLAttributes<T> & { disabled?: boolean; type?: 'button' | 'submit' | 'reset' };
  export type AnchorHTMLAttributes<T> = HTMLAttributes<T> & { href?: string };
}

declare module 'react/jsx-runtime' {
  import type { ReactNode, Key } from 'react';
  export namespace JSX {
    type Element = ReactNode;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    type ElementType = string | ((props: any) => ReactNode);
    interface ElementChildrenAttribute { children: object }
    interface IntrinsicAttributes { key?: Key | null }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    type DOMProps<T = any> = {
      onClick?: (e: import('react').MouseEvent<T>) => void;
      onChange?: (e: import('react').ChangeEvent<T>) => void;
      onInput?: (e: import('react').ChangeEvent<T>) => void;
      onSubmit?: (e: import('react').FormEvent<T>) => void;
      onKeyDown?: (e: import('react').KeyboardEvent<T>) => void;
      onKeyUp?: (e: import('react').KeyboardEvent<T>) => void;
      onPointerDown?: (e: import('react').PointerEvent<T>) => void;
      onPointerMove?: (e: import('react').PointerEvent<T>) => void;
      onPointerUp?: (e: import('react').PointerEvent<T>) => void;
      onPointerLeave?: (e: import('react').PointerEvent<T>) => void;
      onPointerEnter?: (e: import('react').PointerEvent<T>) => void;
      onWheel?: (e: import('react').WheelEvent<T>) => void;
      onFocus?: (e: import('react').SyntheticEvent<T>) => void;
      onBlur?: (e: import('react').SyntheticEvent<T>) => void;
      onContextMenu?: (e: import('react').MouseEvent<T>) => void;
      onMouseDown?: (e: import('react').MouseEvent<T>) => void;
      onMouseUp?: (e: import('react').MouseEvent<T>) => void;
      onMouseEnter?: (e: import('react').MouseEvent<T>) => void;
      onMouseLeave?: (e: import('react').MouseEvent<T>) => void;
      onDoubleClick?: (e: import('react').MouseEvent<T>) => void;
      onDragStart?: (e: import('react').DragEvent<T>) => void;
      onDragEnd?: (e: import('react').DragEvent<T>) => void;
      onDragOver?: (e: import('react').DragEvent<T>) => void;
      onDragEnter?: (e: import('react').DragEvent<T>) => void;
      onDragLeave?: (e: import('react').DragEvent<T>) => void;
      onDrop?: (e: import('react').DragEvent<T>) => void;
      ref?: ((el: T | null) => void) | import('react').RefObject<T | null>;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      [attr: string]: any;
    };
    interface IntrinsicElements {
      input: DOMProps<HTMLInputElement>; select: DOMProps<HTMLSelectElement>; textarea: DOMProps<HTMLTextAreaElement>;
      canvas: DOMProps<HTMLCanvasElement>; svg: DOMProps<SVGSVGElement>; button: DOMProps<HTMLButtonElement>;
      form: DOMProps<HTMLFormElement>; a: DOMProps<HTMLAnchorElement>;
      [el: string]: DOMProps;
    }
  }
  export const jsx: unknown;
  export const jsxs: unknown;
  export const Fragment: unknown;
}

declare module 'react-dom/client' {
  import type { ReactNode } from 'react';
  export function createRoot(el: Element | DocumentFragment): { render(node: ReactNode): void; unmount(): void };
}

