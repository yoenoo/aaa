import { getContext, setContext } from 'svelte';

const KEY = Symbol('expand-all');

export type ExpandState = {
  readonly value: 'expanded' | 'collapsed' | 'auto';
};

export function setExpandContext(ctx: ExpandState): void {
  setContext(KEY, ctx);
}

export function getExpandContext(): ExpandState {
  return getContext<ExpandState>(KEY) ?? { value: 'auto' };
}
