import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../logics/test/hookHarness.js";

test("closed VR log renders no body or subscribers and retains its saved view across reopen", async () => {
    const runtime = hooks();
    let reads = 0;
    const LogBox = () => null;
    const { VrLogWindow } = await loadModule(new URL("./VrLogWindow.jsx", import.meta.url), runtime, {
        "@logics_configs": { useVr: () => {
            reads++;
            return { currentOverlayVrPanelLocked: { data: false }, currentOverlayVrPanelFontSize: { data: 24 } };
        } },
        "../app/main_page/main_section/message_container/log_box/LogBox": { LogBox },
        "./VrWindow": { VrWindow: () => null },
    });
    assert.equal(runtime.render(VrLogWindow, { open: false }), null);
    assert.equal(reads, 0);
    const opened = runtime.render(VrLogWindow, { open: true });
    const bodyRuntime = hooks();
    const body = bodyRuntime.render(opened.type, opened.props);
    const savedView = find(body, node => node.type === LogBox).props.savedView;
    assert.equal(reads, 1);
    savedView.current = { follow: false, scrollTop: 123 };
    bodyRuntime.unmount();
    assert.equal(runtime.render(VrLogWindow, { open: false }), null);
    // Even repeated parent updates while closed never reach the body/useVr/LogBox.
    assert.equal(runtime.render(VrLogWindow, { open: false }), null);
    assert.equal(reads, 1);
    const reopened = runtime.render(VrLogWindow, { open: true });
    assert.equal(reopened.props.savedView, savedView);
    assert.deepEqual(reopened.props.savedView.current, { follow: false, scrollTop: 123 });
    runtime.unmount();
});
