import { readFile } from "node:fs/promises";
import Babel from "@babel/standalone";
import React from "react";
import * as jsx from "react/jsx-runtime";
import clsx from "clsx";
import { atom, createStore } from "jotai/vanilla";

// Explicit renders exercise production handlers without a browser. Effects clean
// up on dependency changes as well as unmount, so listener churn is observable.
export function hooks() {
    const slots = [], effects = [], targets = [], setters = new Map();
    let index = 0, store = createStore();
    const changed = (slot, deps) => !slot || !deps || deps.length !== slot.deps?.length ||
        deps.some((value, i) => !Object.is(value, slot.deps[i]));
    const memo = (factory, deps) => {
        const i = index++;
        if (changed(slots[i], deps)) slots[i] = { deps, value: factory() };
        return slots[i].value;
    };
    const effect = (fn, deps) => {
        const i = index++;
        if (changed(slots[i], deps)) effects.push(() => {
            slots[i]?.cleanup?.();
            slots[i] = { deps, cleanup: fn() };
        });
    };
    const api = { ...React,
        useState: initial => {
            const i = index++;
            if (!(i in slots)) slots[i] = { value: typeof initial === "function" ? initial() : initial };
            return [slots[i].value, value => { slots[i].value = typeof value === "function" ? value(slots[i].value) : value; }];
        },
        useRef: initial => memo(() => ({ current: initial }), []),
        useId: () => memo(() => `test-${index}`, []),
        useMemo: memo, useCallback: (fn, deps) => memo(() => fn, deps),
        useEffect: effect, useLayoutEffect: effect,
    };
    const jotai = {
        atom: initial => { const target = atom(initial); targets.push(target); return target; },
        useStore: () => store,
        useAtom: target => {
            if (!setters.has(target)) setters.set(target, value => store.set(target, value));
            return [store.get(target), setters.get(target)];
        },
    };
    return { api, jotai, targets, get store() { return store; }, set store(value) { store = value; },
        render: (component, props, attach = () => {}) => {
            index = 0;
            const tree = component(props);
            attach(tree);
            effects.splice(0).forEach(fn => fn());
            return tree;
        },
        unmount: () => { for (const slot of slots) { slot?.cleanup?.(); if (slot) slot.cleanup = undefined; } },
    };
}

export async function loadModule(url, runtime, imports = {}) {
    const source = await readFile(url, "utf8");
    const { code } = Babel.transform(source, {
        presets: [["react", { runtime: "automatic" }]], plugins: ["transform-modules-commonjs"],
    });
    const dependencies = { react: runtime.api, "react/jsx-runtime": jsx, clsx, jotai: runtime.jotai,
        "@useI18n": { useI18n: () => ({ t: key => key }) },
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: async () => true }) }, ...imports };
    const require = name => {
        if (name.endsWith(".module.scss")) return new Proxy({}, { get: (_, key) => key === "__esModule" ? false : key });
        if (name.endsWith(".svg?react")) return () => null;
        if (name in dependencies) return dependencies[name];
        throw new Error(`Unexpected dependency: ${name}`);
    };
    const exports = {};
    new Function("require", "exports", code)(require, exports);
    return exports;
}

export function find(tree, predicate) {
    if (!tree || typeof tree !== "object") return null;
    if (predicate(tree)) return tree;
    for (const child of React.Children.toArray(tree.props?.children)) {
        const found = find(child, predicate);
        if (found) return found;
    }
    return null;
}

export function eventTarget() {
    const listeners = new Map(), added = [], removed = [];
    return { added, removed,
        addEventListener: (type, fn) => {
            added.push([type, fn]);
            if (!listeners.has(type)) listeners.set(type, new Set());
            listeners.get(type).add(fn);
        },
        removeEventListener: (type, fn) => { removed.push([type, fn]); listeners.get(type)?.delete(fn); },
        dispatch: (type, event) => { for (const fn of listeners.get(type) ?? []) fn(event); },
    };
}
