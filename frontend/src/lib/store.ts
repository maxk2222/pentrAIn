import { create } from "zustand";
import { api, type Session } from "./api";

interface AppState {
  activeSession: Session | null;
  loadActiveSession: () => Promise<void>;
  setActiveSession: (s: Session | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  activeSession: null,
  loadActiveSession: async () => {
    try {
      const s = await api.get<Session | null>("/api/sessions/active");
      set({ activeSession: s });
    } catch {
      set({ activeSession: null });
    }
  },
  setActiveSession: (s) => set({ activeSession: s }),
}));
