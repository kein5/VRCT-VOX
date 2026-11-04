import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { hooks, loadModule, find, eventTarget, stubGlobals } from '../../logics/test/hookHarness.js';
import { deferred, flush } from '../../logics/test/bridgeHarness.js';
import * as chatboxLength from '../../logics/common/chatboxLength.js';

async function setup(testContext) {
    const runtime = hooks(), properties = new Map(), callbacks = {}, removals = [], submissions = [];
    let context = { language: 'ja', enter_to_send: true, clear_on_send: true, ui_scaling: 150, font_family: 'Noto Sans JP' };
    let focusCount = 0, hideCount = 0, contextRead = () => Promise.resolve(context);
    const field = { focus: () => focusCount++ };
    const i18n = { changeLanguage: async () => {} };
    const window = eventTarget();
    stubGlobals(testContext, { window, document: { documentElement: { style: { setProperty: (key, value) => properties.set(key, value) } } } });
    const bridge = {
        context: () => contextRead(),
        onOpen: async callback => { callbacks.open = callback; return () => removals.push('open'); },
        onContextChanged: async callback => { callbacks.context = callback; return () => removals.push('context'); },
        hide: async () => { hideCount++; },
        submit: request => { submissions.push(request); return bridge.handoff.promise; },
        handoff: deferred(),
    };
    const { QuickChat } = await loadModule(new URL('./QuickChat.jsx', import.meta.url), runtime, {
        '@useI18n': { useI18n: () => ({ t: key => key, i18n }) },
        '../../logics/quickChat/bridge': { quickChatBridge: bridge },
        '../../logics/common/chatboxLength': chatboxLength,
    });
    const render = () => runtime.render(QuickChat, { bridge }, tree => {
        tree.ref.current = {};
        find(tree, node => node.type === 'textarea').ref.current = field;
    });
    render(); await flush(); render();
    return { runtime, render, properties, callbacks, removals, bridge, submissions,
        setContext: next => { context = { ...context, ...next }; },
        setRead: read => { contextRead = read; },
        get focusCount() { return focusCount; }, get hideCount() { return hideCount; },
        field: () => find(render(), node => node.type === 'textarea').props,
    };
}

test('Quick Chat applies saved scale and a literal local font, then updates without stealing focus or changing the draft', async t => {
    const subject = await setup(t);
    assert.equal(subject.properties.get('font-size'), '93.75%');
    assert.equal(subject.properties.get('--font_family'), '"Noto Sans JP"');
    subject.field().onChange({ target: { value: '書きかけの日本語' } });
    const before = subject.focusCount;
    const font = 'Local "Quoted" \\ Font';
    subject.setContext({ ui_scaling: 200, font_family: font });
    await subject.callbacks.context({ payload: { ui_scaling: 40, font_family: 'ignored' } });
    subject.render();
    assert.equal(subject.properties.get('font-size'), '125%');
    assert.equal(subject.properties.get('--font_family'), JSON.stringify(font));
    assert.equal(subject.field().value, '書きかけの日本語');
    assert.equal(subject.focusCount, before);
    await subject.callbacks.open();
    assert.equal(subject.focusCount, before + 1);
    subject.runtime.unmount(); await flush();
    assert.deepEqual(subject.removals.sort(), ['context', 'open']);
});

test('an older context read cannot overwrite a later settings update', async t => {
    const subject = await setup(t), older = deferred();
    const before = subject.focusCount;
    subject.setRead(() => older.promise);
    const opening = subject.callbacks.open();
    subject.setRead(async () => ({ language: 'ja', ui_scaling: 180, font_family: 'New font' }));
    await subject.callbacks.context();
    older.resolve({ language: 'en', ui_scaling: 100, font_family: 'Old font' });
    await opening;
    subject.render();
    assert.equal(subject.properties.get('font-size'), '112.5%');
    assert.equal(subject.properties.get('--font_family'), '"New font"');
    assert.equal(subject.focusCount, before + 1); // The outstanding open still focuses once.
    subject.runtime.unmount();
});

test('appearance updates preserve Quick Chat IME, repeat, pending and failed-handoff draft guards', async t => {
    const subject = await setup(t);
    subject.field().onChange({ target: { value: 'こんにちは' } });
    const enter = extra => subject.field().onKeyDown({ key: 'Enter', nativeEvent: {}, preventDefault() {}, ...extra });
    subject.field().onCompositionStart(); enter(); subject.field().onCompositionEnd();
    enter({ nativeEvent: { isComposing: true } }); enter({ keyCode: 229 }); enter({ repeat: true }); enter({ shiftKey: true });
    assert.equal(subject.submissions.length, 0);
    enter(); enter();
    assert.equal(subject.submissions.length, 1);
    subject.setContext({ ui_scaling: 160 }); await subject.callbacks.context();
    subject.render().props.onKeyDown({ key: 'Escape', nativeEvent: {}, preventDefault() {} });
    assert.equal(subject.hideCount, 1);
    assert.equal(subject.field().value, 'こんにちは');
    subject.bridge.handoff.resolve(false); await flush();
    assert.equal(subject.field().value, 'こんにちは');
    assert.equal(subject.submissions.length, 1);
    subject.runtime.unmount();
});

test('minimum-size layout keeps scrollable overflow, wrapping actions and nonshrinking status text', async () => {
    const css = await readFile(new URL('./QuickChat.module.scss', import.meta.url), 'utf8');
    assert.match(css, /height: 100%;[^\n]*overflow: auto/);
    assert.match(css, /textarea \{[^\n]*min-height: 3rem/);
    assert.match(css, /\.actions \{\s*display: flex; flex-wrap: wrap; flex-shrink: 0/);
    assert.match(css, /\.length_warning \{\s*display: flex; flex-wrap: wrap; flex-shrink: 0/);
    assert.doesNotMatch(css, /https?:|@font-face/);
});

test('main publishes saved appearance on initial configuration and later changes', async () => {
    const runtime = hooks(), contexts = [];
    let scale = 150, font = 'Noto Sans JP';
    const { QuickChatController } = await loadModule(new URL('../app/_app_controllers/QuickChatController.jsx', import.meta.url), runtime, {
        '@tauri-apps/api/core': { invoke: async (name, args) => { if (name === 'quick_chat_configure') contexts.push(args.context); } },
        '@tauri-apps/api/event': { listen: async () => () => {} },
        '@useI18n': { useI18n: () => ({ i18n: { language: 'ja' } }) },
        '../../../logics/common/useMessage': { useMessage: () => ({ sendMessage() { assert.fail('configuration must not send'); } }) },
        '@logics_common': {
            useIsBackendReady: () => ({ currentIsBackendReady: { data: true } }),
            useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: false } }),
            useIsSoftwareUpdating: () => ({ currentIsSoftwareUpdating: { data: false } }),
        },
        '@logics_configs': {
            useAppearance: () => ({ currentSendMessageButtonType: { data: 'show' }, currentUiScaling: { data: scale }, currentSelectedFontFamily: { data: font } }),
            useOthers: () => ({ currentEnableAutoClearMessageInputBox: { data: true } }),
        },
    });
    runtime.render(QuickChatController); await flush();
    assert.equal(contexts[0].ui_scaling, 150);
    assert.equal(contexts[0].font_family, 'Noto Sans JP');
    scale = 200; font = 'Local font';
    runtime.render(QuickChatController); await flush();
    assert.equal(contexts.at(-1).ui_scaling, 200);
    assert.equal(contexts.at(-1).font_family, 'Local font');
    runtime.unmount();
});
