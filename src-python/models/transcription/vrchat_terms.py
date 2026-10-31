"""Built-in VRChat vocabulary for realtime ASR. Data only; reviewed by hand.

Each entry is a speech.cpp keyword: the written form the text should hold,
then "=" and the kana readings the recognizer would otherwise write. An entry
without readings only boosts its own spelling (Haas: "a keyword Haas already
writes as listed needs none").

Haas rewrites every listed reading into the written form, in hiragana or
katakana, so a reading must not also be an everyday word. That is why "Udon"
(うどん is food) and "BOOTH" (ブース is also a Vket exhibit) have no reading.
Keep the list short: each keyword adds a small chance of a word that was not
said (speech.cpp docs/models/fastconformer.md, "A custom vocabulary").
"""

VRCHAT_TERMS = (
    # Platform and its features.
    'VRChat=ブイアールチャット,ブイチャ',
    'VRC=ブイアールシー',
    'インスタンス',
    'ワールド',
    'アバター',
    'ポータル',
    'ミラー',
    'フレンド',
    'フレンド申請=ふれんどしんせい',
    'ブロック',
    'ミュート',
    'ジョイン',
    'グループ',
    'Public=パブリック',
    'Friends+=フレンズプラス',
    'Invite+=インバイトプラス',
    'トラストランク',
    'Visitor=ビジター',
    'New User=ニューユーザー',
    'Known User=ノウンユーザー',
    'Trusted User=トラステッドユーザー',
    'Udon',
    'UdonSharp=ウドンシャープ',
    'VRChat SDK',
    'SDK=エスディーケー',
    'VCC=ブイシーシー',
    'Creator Companion=クリエイターコンパニオン',
    'Unity=ユニティ',
    'OSC=オーエスシー',
    'PhysBones=フィズボーン',
    'Expression Menu=エクスプレッションメニュー',
    # Hardware and stores.
    'SteamVR=スチームブイアール',
    'Quest=クエスト',
    'PCVR=ピーシーブイアール',
    'Index=インデックス',
    'ベースステーション',
    'トラッカー',
    'フルトラ',
    'フルトラッキング',
    'BOOTH',
    'VRM=ブイアールエム',
    'Discord=ディスコード',
    'Vket=ブイケット',
    # Community words.
    '集会=しゅうかい',
    'お砂糖=おさとう',
    '無言勢=むごんぜい',
    'Quest勢=くえすとぜい',
    'PC勢=ぴーしーぜい',
    'デスクトップ勢=ですくとっぷぜい',
    '改変=かいへん',
)
