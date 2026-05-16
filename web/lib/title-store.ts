import { create } from "zustand";

// Auto-generated chat titles keyed by thread id. Titles are produced by
// /api/title from the first user message; the runtime's local thread state
// doesn't ship with title generation so we maintain it client-side here.
type TitleState = {
  titles: Record<string, string>;
  pending: Record<string, boolean>;
  setTitle: (threadId: string, title: string) => void;
  markPending: (threadId: string) => void;
  clearPending: (threadId: string) => void;
};

export const useTitleStore = create<TitleState>((set) => ({
  titles: {},
  pending: {},
  setTitle: (threadId, title) =>
    set((s) => ({
      titles: { ...s.titles, [threadId]: title },
      pending: { ...s.pending, [threadId]: false },
    })),
  markPending: (threadId) =>
    set((s) => ({ pending: { ...s.pending, [threadId]: true } })),
  clearPending: (threadId) =>
    set((s) => ({ pending: { ...s.pending, [threadId]: false } })),
}));
