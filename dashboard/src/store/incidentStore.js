// ─── incidentStore.js ──────────────────────────────────────────────────────────
// Optional Zustand store. Currently the Dashboard page manages state directly
// via useState. Migrate here if state complexity grows (e.g. multi-page routing,
// shared filters, or notification queue).
//
// Usage:
//   import { useIncidentStore } from "../store/incidentStore";
//   const { selectedId, setSelectedId } = useIncidentStore();

import { create } from "zustand";

export const useIncidentStore = create((set) => ({
    selectedId: null,
    prevStatusMap: {},
    newIds: new Set(),

    setSelectedId: (id) => set({ selectedId: id }),
    setPrevStatus: (id, s) => set(state => ({ prevStatusMap: { ...state.prevStatusMap, [id]: s } })),
    addNewId: (id) => set(state => ({ newIds: new Set([...state.newIds, id]) })),
    removeNewId: (id) => set(state => { const n = new Set(state.newIds); n.delete(id); return { newIds: n }; }),
}));