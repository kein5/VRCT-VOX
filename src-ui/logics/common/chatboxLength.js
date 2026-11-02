// VRChat のチャットボックスに表示されるのは144文字まで (OSC の /chatbox/input)。
// 超えても送信は止めず、入力欄のそばで知らせるだけにする。VRChat (C#) の文字列と同じく
// UTF-16 の長さで数える (絵文字は2文字になる)
export const CHATBOX_MAX_LENGTH = 144;

export const chatboxOverflowLength = (text) =>
    typeof text === "string" && text.length > CHATBOX_MAX_LENGTH ? text.length : null;
