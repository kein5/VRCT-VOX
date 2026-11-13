import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const variables = Object.fromEntries([...read("../_index_css/variables.css").matchAll(/(--[\w-]+):\s*([^;]+);/g)]
    .map(([, key, value]) => [key, value.trim()]));
const color = token => {
    const value = variables[token] ?? token;
    const alias = /^var\((--[\w-]+)\)$/.exec(value);
    return alias ? color(alias[1]) : value;
};
const luminance = token => {
    const rgb = color(token).slice(1).match(/../g).map(channel => parseInt(channel, 16) / 255)
        .map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
};
const contrast = (fg, bg) => {
    const values = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
    return (values[0] + .05) / (values[1] + .05);
};
const token = (css, pattern) => { const match = css.match(pattern); assert.ok(match, String(pattern)); return match[1]; };
const bg = /background(?:-color)?:\s*var\((--[\w-]+)\)/;
const fg = /color:\s*var\((--[\w-]+)\)/;
const canvas = token(read("MainPage.module.scss"), bg);
const top = read("main_section/top_bar/right_side_components/_buttons/OpenQuickSettingButton.module.scss");
const close = read("../others/modal_controller/ModalController.module.scss").split(".close_button {")[1];
const off = token(top.split("&.is_disabled {")[1].split("}")[0], fg);
const messages = read("main_section/message_container/log_box/message_container/MessageContainer.module.scss").split(".category {")[1];
const pairs = [
    ["top-bar off resting", off, canvas],
    ["top-bar off hover", off, token(top.split("&:hover {")[1], bg)],
    ["top-bar off pressed", off, token(top.split("&:active {")[1], bg)],
    ["quick-dialog close resting", token(close, fg), token(close, bg)],
    ["quick-dialog close hover", token(close, fg), token(close.split("&:hover {")[1], bg)],
    ["quick-dialog close pressed", token(close, fg), token(close.split("&:active {")[1], bg)],
    ["received category", token(messages.split("&.received_message {")[1], fg), canvas],
    ["OCR category", token(messages.split("&.ocr_category {")[1], fg), canvas],
];
for (const [name, foreground, background] of pairs) {
    test(`${name}: actual CSS pair meets 4.5:1 for small text`, context => {
        const ratio = contrast(foreground, background);
        context.diagnostic(`${color(foreground)} on ${color(background)}: ${ratio.toFixed(3)}:1 (opaque sRGB)`);
        assert.ok(ratio >= 4.5, `${name}: ${ratio}`);
    });
}
